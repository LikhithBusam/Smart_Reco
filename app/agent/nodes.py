"""LangGraph nodes. See ARCHITECTURE.md §5 for the graph shape and the
reasoning behind each node's behavior."""

import hashlib
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update

from app.agent.state import AgentState
from app.config import settings
from app.db.models import AgentRun, Event, Recommendation
from app.db.session import AsyncSessionLocal
from app.services import mesh_client
from app.services.redis_client import get_redis
from app.vector import chroma_client

logger = logging.getLogger(__name__)

MAX_REFINE_RETRIES = 2
MIN_RETRIEVAL_RESULTS = 1


async def load_activity(state: AgentState) -> dict:
    user_id = UUID(state["user_id"])
    async with AsyncSessionLocal() as db:
        events = (
            await db.execute(
                select(Event).where(Event.user_id == user_id).order_by(Event.created_at.desc()).limit(50)
            )
        ).scalars().all()
        active_rec = (
            await db.execute(
                select(Recommendation)
                .where(Recommendation.user_id == user_id, Recommendation.is_active.is_(True))
                .order_by(Recommendation.generated_at.desc())
            )
        ).scalars().first()

    return {
        "raw_events": [
            {
                "event_type": e.event_type,
                "entity_type": e.entity_type,
                "entity_id": str(e.entity_id) if e.entity_id else None,
                "metadata": e.event_metadata,
            }
            for e in events
        ],
        "active_recommendation": (
            {
                "id": str(active_rec.id),
                "narrative": active_rec.narrative,
                "product_ids": [str(pid) for pid in active_rec.product_ids],
                "generated_at": active_rec.generated_at.isoformat(),
            }
            if active_rec
            else None
        ),
    }


async def should_trigger(state: AgentState) -> dict:
    user_id = state["user_id"]
    pending = int(await get_redis().get(f"pending_signal:{user_id}") or 0)

    if pending >= settings.trigger_event_threshold:
        return {"should_trigger": True, "trigger_reason": "event_threshold"}

    active = state.get("active_recommendation")
    if active is None or _is_stale(active["generated_at"]):
        return {"should_trigger": True, "trigger_reason": "time_ttl"}

    return {"should_trigger": False, "trigger_reason": None}


def _is_stale(generated_at_iso: str) -> bool:
    generated_at = datetime.fromisoformat(generated_at_iso)
    return (datetime.now(timezone.utc) - generated_at) >= timedelta(hours=settings.recommendation_ttl_hours)


def route_after_trigger(state: AgentState) -> str:
    return "analyze_interest" if state.get("should_trigger") else "serve_cached"


async def analyze_interest(state: AgentState) -> dict:
    events = state.get("raw_events", [])
    cache_key = _interest_cache_key(state["user_id"], events)

    redis_client = get_redis()
    cached = await redis_client.get(cache_key)
    if cached:
        return {"interest_summary": cached}

    summary = mesh_client.chat(
        [
            {
                "role": "system",
                "content": (
                    "Summarize this user's shopping interest in one sentence, grounded only "
                    "in the activity listed below. Do not mention any product by name."
                ),
            },
            {"role": "user", "content": json.dumps(events)},
        ]
    )
    await redis_client.set(cache_key, summary, ex=settings.recommendation_ttl_hours * 3600)
    return {"interest_summary": summary}


def _interest_cache_key(user_id: str, events: list[dict]) -> str:
    digest = hashlib.sha256((user_id + json.dumps(events, sort_keys=True)).encode()).hexdigest()
    return f"interest_cache:{digest}"


def _infer_category_filter(raw_events: list[dict]) -> dict | None:
    """Retrieval polish (ARCHITECTURE.md §12 bonus): narrow to the category the
    user has clearly been focused on, inferred from event metadata tracker.js
    already sends. Needs a real majority, not just a plurality of 2."""
    categories = [
        e["metadata"]["category"] for e in raw_events if e.get("metadata") and e["metadata"].get("category")
    ]
    if len(categories) < 2:
        return None
    dominant, count = Counter(categories).most_common(1)[0]
    if count / len(categories) <= 0.5:  # a tie isn't a majority
        return None
    return {"category": dominant}


async def retrieve(state: AgentState) -> dict:
    retry_count = state.get("retry_count", 0)
    # Widening n_results and dropping the filter is the whole "refine" strategy —
    # smarter query rewriting is a further upgrade, add if recall stays weak.
    n_results = 5 * (retry_count + 1)
    where = None if retry_count > 0 else _infer_category_filter(state.get("raw_events", []))
    results = chroma_client.query_products(state["interest_summary"], n_results=n_results, where=where)

    ids = results["ids"][0] if results.get("ids") else []
    documents = results["documents"][0] if results.get("documents") else []
    metadatas = results["metadatas"][0] if results.get("metadatas") else []

    products = [
        {"id": pid, "document": doc, "metadata": meta}
        for pid, doc, meta in zip(ids, documents, metadatas)
    ]
    return {"retrieved_products": products}


def evaluate_retrieval(state: AgentState) -> dict:
    return {"retrieval_ok": len(state.get("retrieved_products", [])) >= MIN_RETRIEVAL_RESULTS}


def route_after_evaluation(state: AgentState) -> str:
    if state.get("retrieval_ok") or state.get("retry_count", 0) >= MAX_REFINE_RETRIES:
        return "generate_recommendation"
    return "refine_query"


def refine_query(state: AgentState) -> dict:
    return {"retry_count": state.get("retry_count", 0) + 1}


class _RecommendationOutput(BaseModel):
    narrative: str
    product_ids: list[str]


async def generate_recommendation(state: AgentState) -> dict:
    retrieved = state.get("retrieved_products", [])
    catalog = "\n".join(f"- {p['id']}: {p['document']}" for p in retrieved)
    messages = [
        {
            "role": "system",
            "content": (
                'Write a short, persuasive recommendation narrative for this user. Respond as JSON: '
                '{"narrative": str, "product_ids": [str]}. product_ids MUST only contain IDs from the '
                "catalog below — never invent one."
            ),
        },
        {"role": "user", "content": f"User interest: {state['interest_summary']}\n\nCatalog:\n{catalog}"},
    ]

    parsed = _parse_recommendation(mesh_client.chat(messages, json_mode=True))
    if parsed is None:
        retry_prompt = messages + [
            {"role": "user", "content": "That response wasn't valid JSON matching the schema. Try again."}
        ]
        parsed = _parse_recommendation(mesh_client.chat(retry_prompt, json_mode=True))

    if parsed is None:
        logger.warning(
            "generate_recommendation: two invalid responses, failing closed for user %s", state.get("user_id")
        )
        return {"recommendation": None}

    return {"recommendation": {"narrative": parsed.narrative, "product_ids": parsed.product_ids}}


def _parse_recommendation(raw: str) -> _RecommendationOutput | None:
    try:
        return _RecommendationOutput.model_validate_json(raw)
    except ValidationError:
        return None


async def persist(state: AgentState) -> dict:
    user_id = UUID(state["user_id"])
    recommendation = state.get("recommendation")
    retrieved_ids = {p["id"] for p in state.get("retrieved_products", [])}

    async with AsyncSessionLocal() as db:
        run = AgentRun(
            user_id=user_id,
            trigger_type=state.get("trigger_reason"),
            status="failed" if recommendation is None else "completed",
            retry_count=state.get("retry_count", 0),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)
        await db.flush()

        if recommendation is not None:
            # The real grounding guarantee: drop anything the model referenced that wasn't
            # actually retrieved. The prompt asked nicely; this is what enforces it.
            grounded_ids = [pid for pid in recommendation["product_ids"] if pid in retrieved_ids]
            if grounded_ids:
                await db.execute(
                    update(Recommendation)
                    .where(Recommendation.user_id == user_id, Recommendation.is_active.is_(True))
                    .values(is_active=False)
                )
                db.add(
                    Recommendation(
                        user_id=user_id,
                        narrative=recommendation["narrative"],
                        product_ids=[UUID(pid) for pid in grounded_ids],
                        trigger_reason=state.get("trigger_reason"),
                        is_active=True,
                        agent_run_id=run.id,
                    )
                )
            else:
                logger.warning("persist: model's product_ids had zero overlap with retrieved set, skipping write")

        await db.commit()

    # Resetting this is what stops the same events re-triggering a run past THRESHOLD forever.
    await get_redis().delete(f"pending_signal:{state['user_id']}")
    return {}


async def serve_cached_recommendation(state: AgentState) -> dict:
    async with AsyncSessionLocal() as db:
        db.add(
            AgentRun(
                user_id=UUID(state["user_id"]),
                trigger_type="none",
                status="cache_hit",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    return {"recommendation": state.get("active_recommendation")}

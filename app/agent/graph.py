"""The compiled graph plus its one public entry point, run_agent(). See
ARCHITECTURE.md §5 for the shape and §6 for why the lock/reset matter."""

import logging
from datetime import datetime, timezone
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    analyze_interest,
    evaluate_retrieval,
    generate_recommendation,
    load_activity,
    persist,
    refine_query,
    retrieve,
    route_after_evaluation,
    route_after_trigger,
    serve_cached_recommendation,
    should_trigger,
)
from app.agent.state import AgentState
from app.db.models import AgentRun
from app.db.session import AsyncSessionLocal
from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

_LOCK_TTL_MS = 60_000

_builder = StateGraph(AgentState)
_builder.add_node("load_activity", load_activity)
_builder.add_node("check_trigger", should_trigger)
_builder.add_node("analyze_interest", analyze_interest)
_builder.add_node("retrieve", retrieve)
_builder.add_node("evaluate_retrieval", evaluate_retrieval)
_builder.add_node("refine_query", refine_query)
_builder.add_node("generate_recommendation", generate_recommendation)
_builder.add_node("persist", persist)
_builder.add_node("serve_cached", serve_cached_recommendation)

_builder.add_edge(START, "load_activity")
_builder.add_edge("load_activity", "check_trigger")
_builder.add_conditional_edges("check_trigger", route_after_trigger)
_builder.add_edge("analyze_interest", "retrieve")
_builder.add_edge("retrieve", "evaluate_retrieval")
_builder.add_conditional_edges("evaluate_retrieval", route_after_evaluation)
_builder.add_edge("refine_query", "retrieve")
_builder.add_edge("generate_recommendation", "persist")
_builder.add_edge("persist", END)
_builder.add_edge("serve_cached", END)

compiled_graph = _builder.compile()


async def run_agent(user_id: str) -> dict | None:
    """Concurrency-guarded entry point. A second call for the same user while
    one is already running skips entirely rather than starting a duplicate
    LangGraph run (and a duplicate LLM call)."""
    redis_client = get_redis()
    lock_key = f"agent_lock:{user_id}"

    acquired = await redis_client.set(lock_key, "1", nx=True, px=_LOCK_TTL_MS)
    if not acquired:
        logger.info("Agent already running for user %s, skipping", user_id)
        return None

    try:
        result = await compiled_graph.ainvoke({"user_id": user_id, "retry_count": 0})
        return result.get("recommendation")
    except Exception:
        # A node raising (Mesh network/auth error, etc.) must still leave a trace -
        # discovered via a real live run against a bad key, not a mock.
        logger.exception("Agent run crashed for user %s", user_id)
        await _log_crashed_run(user_id)
        return None
    finally:
        await redis_client.delete(lock_key)


async def _log_crashed_run(user_id: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            AgentRun(
                user_id=UUID(user_id),
                trigger_type="error",
                status="failed",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

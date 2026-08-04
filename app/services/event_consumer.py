"""Drains the Redis events queue into Postgres and increments each affected
user's pending_signal counter in the same tick — tracking and the agent
trigger signal share one pass instead of two. One job on the shared
scheduler (app/services/scheduler.py). See ARCHITECTURE.md §4.
"""

import json
import logging
from uuid import UUID

from app.db.models import Event
from app.db.session import AsyncSessionLocal
from app.services.redis_client import EVENTS_QUEUE_KEY, get_redis

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


async def consume_pending_events() -> None:
    redis_client = get_redis()

    raw_events = await redis_client.lrange(EVENTS_QUEUE_KEY, 0, BATCH_SIZE - 1)
    if not raw_events:
        return
    await redis_client.ltrim(EVENTS_QUEUE_KEY, len(raw_events), -1)

    records = []
    signal_counts: dict[str, int] = {}
    for raw in raw_events:
        try:
            data = json.loads(raw)
            records.append(data)
            signal_counts[data["user_id"]] = signal_counts.get(data["user_id"], 0) + 1
        except (json.JSONDecodeError, KeyError):
            logger.exception("Dropping malformed event payload: %r", raw)

    if not records:
        return

    async with AsyncSessionLocal() as db:
        db.add_all(
            Event(
                user_id=UUID(record["user_id"]),
                event_type=record["event_type"],
                entity_type=record.get("entity_type"),
                entity_id=UUID(record["entity_id"]) if record.get("entity_id") else None,
                event_metadata=record.get("metadata"),
                session_id=record.get("session_id"),
            )
            for record in records
        )
        await db.commit()

    pipe = redis_client.pipeline()
    for user_id, count in signal_counts.items():
        pipe.incrby(f"pending_signal:{user_id}", count)
    await pipe.execute()

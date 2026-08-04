import json
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.services import event_consumer


def _mock_db() -> MagicMock:
    """add_all() is sync on a real AsyncSession, commit() is async — mock
    each accordingly so unawaited-coroutine warnings don't mask real bugs."""
    db = MagicMock()
    db.commit = AsyncMock()
    return db


class _FakeSessionCtx:
    def __init__(self, db: AsyncMock):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_consume_pending_events_drains_queue_and_increments_signal(fake_redis):
    user_id = "33333333-3333-3333-3333-333333333333"
    await fake_redis.lpush(
        event_consumer.EVENTS_QUEUE_KEY,
        json.dumps(
            {
                "user_id": user_id,
                "event_type": "view",
                "entity_type": "product",
                "entity_id": None,
                "metadata": None,
                "session_id": "s1",
            }
        ),
        json.dumps(
            {
                "user_id": user_id,
                "event_type": "search",
                "entity_type": None,
                "entity_id": None,
                "metadata": {"query": "agentic ai"},
                "session_id": "s1",
            }
        ),
    )

    mock_db = _mock_db()

    with (
        patch("app.services.event_consumer.get_redis", return_value=fake_redis),
        patch("app.services.event_consumer.AsyncSessionLocal", return_value=_FakeSessionCtx(mock_db)),
    ):
        await event_consumer.consume_pending_events()

    remaining = await fake_redis.lrange(event_consumer.EVENTS_QUEUE_KEY, 0, -1)
    assert remaining == []

    signal = await fake_redis.get(f"pending_signal:{user_id}")
    assert signal == "2"

    mock_db.add_all.assert_called_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_consume_pending_events_is_noop_on_empty_queue(fake_redis):
    mock_db = _mock_db()

    with (
        patch("app.services.event_consumer.get_redis", return_value=fake_redis),
        patch("app.services.event_consumer.AsyncSessionLocal", return_value=_FakeSessionCtx(mock_db)),
    ):
        await event_consumer.consume_pending_events()

    mock_db.add_all.assert_not_called()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_consume_pending_events_drops_malformed_payload_without_crashing(fake_redis):
    await fake_redis.lpush(event_consumer.EVENTS_QUEUE_KEY, "not-valid-json")
    mock_db = _mock_db()

    with (
        patch("app.services.event_consumer.get_redis", return_value=fake_redis),
        patch("app.services.event_consumer.AsyncSessionLocal", return_value=_FakeSessionCtx(mock_db)),
    ):
        await event_consumer.consume_pending_events()  # must not raise

    remaining = await fake_redis.lrange(event_consumer.EVENTS_QUEUE_KEY, 0, -1)
    assert remaining == []
    mock_db.add_all.assert_not_called()

import json
from unittest.mock import patch

import fakeredis.aioredis
import pytest

from app.services import event_consumer
from tests.conftest import FakeSessionCtx, make_mock_db


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

    mock_db = make_mock_db()

    with (
        patch("app.services.event_consumer.get_redis", return_value=fake_redis),
        patch("app.services.event_consumer.AsyncSessionLocal", return_value=FakeSessionCtx(mock_db)),
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
    mock_db = make_mock_db()

    with (
        patch("app.services.event_consumer.get_redis", return_value=fake_redis),
        patch("app.services.event_consumer.AsyncSessionLocal", return_value=FakeSessionCtx(mock_db)),
    ):
        await event_consumer.consume_pending_events()

    mock_db.add_all.assert_not_called()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_consume_pending_events_drops_malformed_payload_without_crashing(fake_redis):
    await fake_redis.lpush(event_consumer.EVENTS_QUEUE_KEY, "not-valid-json")
    mock_db = make_mock_db()

    with (
        patch("app.services.event_consumer.get_redis", return_value=fake_redis),
        patch("app.services.event_consumer.AsyncSessionLocal", return_value=FakeSessionCtx(mock_db)),
    ):
        await event_consumer.consume_pending_events()  # must not raise

    remaining = await fake_redis.lrange(event_consumer.EVENTS_QUEUE_KEY, 0, -1)
    assert remaining == []
    mock_db.add_all.assert_not_called()

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.deps import get_current_user
from app.main import app
from app.services.redis_client import EVENTS_QUEUE_KEY


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def authed_user():
    user = MagicMock()
    user.id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_batch_events_returns_202_and_pushes_to_redis_with_user_id(fake_redis, authed_user):
    with patch("app.api.events.get_redis", return_value=fake_redis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/events/batch",
                json={
                    "events": [
                        {"event_type": "view", "entity_type": "product", "entity_id": None, "metadata": None},
                        {"event_type": "search", "metadata": {"query": "agentic ai"}},
                    ]
                },
            )

    assert response.status_code == 202

    raw = await fake_redis.lrange(EVENTS_QUEUE_KEY, 0, -1)
    assert len(raw) == 2
    parsed = [json.loads(r) for r in raw]
    assert all(p["user_id"] == str(authed_user.id) for p in parsed)
    assert {p["event_type"] for p in parsed} == {"view", "search"}


@pytest.mark.asyncio
async def test_batch_events_requires_authentication():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/events/batch", json={"events": [{"event_type": "view"}]})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_batch_events_rejects_empty_batch(authed_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/events/batch", json={"events": []})

    assert response.status_code == 422

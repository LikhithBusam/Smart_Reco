from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.deps import require_admin
from app.db.session import get_db
from app.main import app


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_db, None)


def _override_db(mock_db):
    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db


@pytest.mark.asyncio
async def test_admin_agent_runs_requires_admin_role():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/agent-runs")

    assert response.status_code == 401  # no auth at all -> get_current_user rejects first


@pytest.mark.asyncio
async def test_admin_agent_runs_returns_runs_for_admin():
    admin_user = MagicMock(role="admin")
    app.dependency_overrides[require_admin] = lambda: admin_user

    run = MagicMock(
        id=uuid4(),
        user_id=uuid4(),
        trigger_type="event_threshold",
        status="completed",
        retry_count=0,
        token_usage=None,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    mock_db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [run]

    async def fake_execute(*args, **kwargs):
        return result

    mock_db.execute = fake_execute
    _override_db(mock_db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/agent-runs")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "completed"
    assert body[0]["trigger_type"] == "event_threshold"

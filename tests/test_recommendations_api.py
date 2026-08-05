from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app


@pytest.fixture
def authed_user():
    user = MagicMock()
    user.id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_user, None)


def _override_db(mock_db):
    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db


@pytest.fixture(autouse=True)
def _clear_db_override():
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_returns_empty_state_when_no_active_recommendation(authed_user, monkeypatch):
    monkeypatch.setattr("app.api.recommendations.run_agent", AsyncMock())

    mock_db = MagicMock()
    rec_result = MagicMock()
    rec_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=rec_result)
    _override_db(mock_db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/recommendations")

    assert response.status_code == 200
    assert response.json() == {"narrative": None, "products": [], "generated_at": None}


@pytest.mark.asyncio
async def test_returns_narrative_with_joined_product_details(authed_user, monkeypatch):
    monkeypatch.setattr("app.api.recommendations.run_agent", AsyncMock())

    product_id = uuid4()
    created_at = datetime.now(timezone.utc)
    fake_product = MagicMock(
        id=product_id,
        title="Agentic AI Systems",
        description="Build autonomous agents",
        category="ai",
        price=Decimal("99.00"),
        is_deleted=False,
        created_at=created_at,
        updated_at=created_at,
    )
    fake_rec = MagicMock(
        narrative="Since you've been exploring agentic AI...",
        product_ids=[product_id],
        generated_at=datetime.now(timezone.utc),
    )

    mock_db = MagicMock()
    rec_result = MagicMock()
    rec_result.scalar_one_or_none.return_value = fake_rec
    products_result = MagicMock()
    products_result.scalars.return_value.all.return_value = [fake_product]
    mock_db.execute = AsyncMock(side_effect=[rec_result, products_result])
    _override_db(mock_db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/recommendations")

    body = response.json()
    assert response.status_code == 200
    assert body["narrative"] == "Since you've been exploring agentic AI..."
    assert body["products"] == [
        {
            "id": str(product_id),
            "title": "Agentic AI Systems",
            "description": "Build autonomous agents",
            "category": "ai",
            "price": "99.00",
            "is_deleted": False,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": created_at.isoformat().replace("+00:00", "Z"),
        }
    ]


@pytest.mark.asyncio
async def test_fires_run_agent_as_background_task_for_the_current_user(authed_user, monkeypatch):
    mock_run_agent = AsyncMock()
    monkeypatch.setattr("app.api.recommendations.run_agent", mock_run_agent)

    mock_db = MagicMock()
    rec_result = MagicMock()
    rec_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=rec_result)
    _override_db(mock_db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/recommendations")

    mock_run_agent.assert_called_once_with(str(authed_user.id))


@pytest.mark.asyncio
async def test_requires_authentication():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/recommendations")

    assert response.status_code == 401

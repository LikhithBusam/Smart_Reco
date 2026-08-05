from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.agent import graph as agent_graph
from tests.conftest import FakeSessionCtx, make_mock_db


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def _db_with_no_history() -> object:
    """load_activity's two queries both resolve against this single mock
    result: no past events, no existing active recommendation."""
    db = make_mock_db()
    db.execute.return_value.scalars.return_value.all.return_value = []
    db.execute.return_value.scalars.return_value.first.return_value = None
    return db


@pytest.mark.asyncio
async def test_run_agent_end_to_end_produces_a_grounded_recommendation(fake_redis):
    db = _db_with_no_history()
    product_id = "44444444-4444-4444-4444-444444444444"
    chroma_results = {
        "ids": [[product_id]],
        "documents": [["Agentic AI Systems course"]],
        "metadatas": [[{"category": "ai"}]],
    }

    with (
        patch("app.agent.graph.get_redis", return_value=fake_redis),
        patch("app.agent.nodes.get_redis", return_value=fake_redis),
        patch("app.agent.nodes.AsyncSessionLocal", return_value=FakeSessionCtx(db)),
        patch("app.agent.nodes.chroma_client.query_products", return_value=chroma_results),
        patch(
            "app.agent.nodes.mesh_client.chat",
            side_effect=[
                "likes agentic AI courses",
                f'{{"narrative": "n", "product_ids": ["{product_id}"]}}',
            ],
        ),
    ):
        result = await agent_graph.run_agent("11111111-1111-1111-1111-111111111111")

    assert result == {"narrative": "n", "product_ids": [product_id]}
    # Lock must be released after a successful run.
    assert await fake_redis.get("agent_lock:11111111-1111-1111-1111-111111111111") is None


@pytest.mark.asyncio
async def test_run_agent_skips_when_lock_already_held(fake_redis):
    await fake_redis.set("agent_lock:u1", "1", px=60_000)

    with (
        patch("app.agent.graph.get_redis", return_value=fake_redis),
        patch("app.agent.graph.compiled_graph.ainvoke", new_callable=AsyncMock) as mock_invoke,
    ):
        result = await agent_graph.run_agent("u1")

    assert result is None
    mock_invoke.assert_not_called()


@pytest.mark.asyncio
async def test_run_agent_releases_lock_even_if_graph_raises(fake_redis):
    with (
        patch("app.agent.graph.get_redis", return_value=fake_redis),
        patch("app.agent.graph.compiled_graph.ainvoke", side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError):
            await agent_graph.run_agent("u1")

    assert await fake_redis.get("agent_lock:u1") is None

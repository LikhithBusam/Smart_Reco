from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

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
        patch("app.agent.graph._log_crashed_run", new_callable=AsyncMock),
    ):
        result = await agent_graph.run_agent("u1")  # must not raise - it's a background task

    assert result is None
    assert await fake_redis.get("agent_lock:u1") is None


@pytest.mark.asyncio
async def test_run_agent_logs_a_failed_agent_run_when_the_graph_raises(fake_redis):
    """Discovered via a real live run against an invalid Mesh key: a node
    exception (auth/network error, not just malformed JSON) used to crash
    silently with zero agent_runs trace. It must be logged as 'failed'."""
    user_id = str(uuid4())
    db = make_mock_db()

    with (
        patch("app.agent.graph.get_redis", return_value=fake_redis),
        patch("app.agent.graph.compiled_graph.ainvoke", side_effect=RuntimeError("mesh auth error")),
        patch("app.agent.graph.AsyncSessionLocal", return_value=FakeSessionCtx(db)),
    ):
        result = await agent_graph.run_agent(user_id)

    assert result is None
    logged_run = next(c.args[0] for c in db.add.call_args_list)
    assert logged_run.status == "failed"
    assert logged_run.user_id == UUID(user_id)

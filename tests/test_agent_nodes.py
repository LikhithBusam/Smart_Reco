from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import fakeredis.aioredis
import pytest

from app.agent import nodes
from tests.conftest import FakeSessionCtx, make_mock_db


# ---- pure routing functions ----


def test_route_after_trigger_goes_to_analyze_when_triggered():
    assert nodes.route_after_trigger({"should_trigger": True}) == "analyze_interest"


def test_route_after_trigger_goes_to_cache_when_not_triggered():
    assert nodes.route_after_trigger({"should_trigger": False}) == "serve_cached"


def test_route_after_evaluation_generates_when_retrieval_ok():
    assert nodes.route_after_evaluation({"retrieval_ok": True, "retry_count": 0}) == "generate_recommendation"


def test_route_after_evaluation_refines_when_weak_and_retries_left():
    assert nodes.route_after_evaluation({"retrieval_ok": False, "retry_count": 0}) == "refine_query"


def test_route_after_evaluation_gives_up_refining_after_max_retries():
    result = nodes.route_after_evaluation({"retrieval_ok": False, "retry_count": nodes.MAX_REFINE_RETRIES})
    assert result == "generate_recommendation"


def test_refine_query_increments_retry_count():
    assert nodes.refine_query({"retry_count": 1}) == {"retry_count": 2}


def test_evaluate_retrieval_true_when_results_present():
    assert nodes.evaluate_retrieval({"retrieved_products": [{"id": "p1"}]}) == {"retrieval_ok": True}


def test_evaluate_retrieval_false_when_empty():
    assert nodes.evaluate_retrieval({"retrieved_products": []}) == {"retrieval_ok": False}


# ---- should_trigger ----


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_should_trigger_fires_on_event_threshold(fake_redis):
    await fake_redis.set("pending_signal:u1", str(nodes.settings.trigger_event_threshold))

    with patch("app.agent.nodes.get_redis", return_value=fake_redis):
        result = await nodes.should_trigger({"user_id": "u1", "active_recommendation": _fresh_recommendation()})

    assert result == {"should_trigger": True, "trigger_reason": "event_threshold"}


@pytest.mark.asyncio
async def test_should_trigger_fires_when_recommendation_is_stale(fake_redis):
    await fake_redis.set("pending_signal:u1", "0")
    stale = _fresh_recommendation(hours_ago=nodes.settings.recommendation_ttl_hours + 1)

    with patch("app.agent.nodes.get_redis", return_value=fake_redis):
        result = await nodes.should_trigger({"user_id": "u1", "active_recommendation": stale})

    assert result == {"should_trigger": True, "trigger_reason": "time_ttl"}


@pytest.mark.asyncio
async def test_should_trigger_short_circuits_when_fresh_and_below_threshold(fake_redis):
    await fake_redis.set("pending_signal:u1", "0")

    with patch("app.agent.nodes.get_redis", return_value=fake_redis):
        result = await nodes.should_trigger({"user_id": "u1", "active_recommendation": _fresh_recommendation()})

    assert result == {"should_trigger": False, "trigger_reason": None}


def _fresh_recommendation(hours_ago: float = 0) -> dict:
    generated_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"id": "r1", "narrative": "x", "product_ids": [], "generated_at": generated_at.isoformat()}


# ---- analyze_interest ----


@pytest.mark.asyncio
async def test_analyze_interest_calls_mesh_on_cache_miss(fake_redis):
    with (
        patch("app.agent.nodes.get_redis", return_value=fake_redis),
        patch("app.agent.nodes.mesh_client.chat", return_value="likes agentic AI courses") as mock_chat,
    ):
        result = await nodes.analyze_interest({"user_id": "u1", "raw_events": [{"event_type": "view"}]})

    assert result == {"interest_summary": "likes agentic AI courses"}
    mock_chat.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_interest_skips_mesh_on_cache_hit(fake_redis):
    events = [{"event_type": "view"}]
    cache_key = nodes._interest_cache_key("u1", events)
    await fake_redis.set(cache_key, "cached summary")

    with (
        patch("app.agent.nodes.get_redis", return_value=fake_redis),
        patch("app.agent.nodes.mesh_client.chat") as mock_chat,
    ):
        result = await nodes.analyze_interest({"user_id": "u1", "raw_events": events})

    assert result == {"interest_summary": "cached summary"}
    mock_chat.assert_not_called()


# ---- generate_recommendation ----


@pytest.mark.asyncio
async def test_generate_recommendation_returns_parsed_output_on_valid_json():
    valid = '{"narrative": "n", "product_ids": ["p1"]}'
    with patch("app.agent.nodes.mesh_client.chat", return_value=valid):
        result = await nodes.generate_recommendation(
            {"interest_summary": "x", "retrieved_products": [{"id": "p1", "document": "d"}]}
        )

    assert result == {"recommendation": {"narrative": "n", "product_ids": ["p1"]}}


@pytest.mark.asyncio
async def test_generate_recommendation_retries_once_on_invalid_json_then_succeeds():
    valid = '{"narrative": "n", "product_ids": ["p1"]}'
    with patch("app.agent.nodes.mesh_client.chat", side_effect=["not json", valid]) as mock_chat:
        result = await nodes.generate_recommendation(
            {"interest_summary": "x", "retrieved_products": [{"id": "p1", "document": "d"}]}
        )

    assert result == {"recommendation": {"narrative": "n", "product_ids": ["p1"]}}
    assert mock_chat.call_count == 2


@pytest.mark.asyncio
async def test_generate_recommendation_fails_closed_after_two_invalid_responses():
    with patch("app.agent.nodes.mesh_client.chat", side_effect=["nope", "still nope"]):
        result = await nodes.generate_recommendation(
            {"interest_summary": "x", "retrieved_products": [{"id": "p1", "document": "d"}]}
        )

    assert result == {"recommendation": None}


# ---- persist: the grounding guarantee ----


@pytest.mark.asyncio
async def test_persist_drops_product_ids_the_model_invented(fake_redis):
    mock_db = make_mock_db()
    state = {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "trigger_reason": "event_threshold",
        "retry_count": 0,
        "retrieved_products": [{"id": "22222222-2222-2222-2222-222222222222"}],
        "recommendation": {
            "narrative": "n",
            "product_ids": [
                "22222222-2222-2222-2222-222222222222",  # real, was retrieved
                "99999999-9999-9999-9999-999999999999",  # hallucinated, was NOT retrieved
            ],
        },
    }

    with (
        patch("app.agent.nodes.AsyncSessionLocal", return_value=FakeSessionCtx(mock_db)),
        patch("app.agent.nodes.get_redis", return_value=fake_redis),
    ):
        await nodes.persist(state)

    added_recommendation = next(c.args[0] for c in mock_db.add.call_args_list if hasattr(c.args[0], "product_ids"))
    assert [str(pid) for pid in added_recommendation.product_ids] == ["22222222-2222-2222-2222-222222222222"]


@pytest.mark.asyncio
async def test_persist_writes_nothing_when_every_id_was_hallucinated(fake_redis):
    mock_db = make_mock_db()
    state = {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "trigger_reason": "event_threshold",
        "retry_count": 0,
        "retrieved_products": [{"id": "22222222-2222-2222-2222-222222222222"}],
        "recommendation": {"narrative": "n", "product_ids": ["99999999-9999-9999-9999-999999999999"]},
    }

    with (
        patch("app.agent.nodes.AsyncSessionLocal", return_value=FakeSessionCtx(mock_db)),
        patch("app.agent.nodes.get_redis", return_value=fake_redis),
    ):
        await nodes.persist(state)

    assert not any(hasattr(c.args[0], "product_ids") for c in mock_db.add.call_args_list)


@pytest.mark.asyncio
async def test_persist_resets_pending_signal_counter(fake_redis):
    await fake_redis.set("pending_signal:33333333-3333-3333-3333-333333333333", "7")
    mock_db = make_mock_db()
    state = {
        "user_id": "33333333-3333-3333-3333-333333333333",
        "trigger_reason": "event_threshold",
        "retry_count": 0,
        "retrieved_products": [],
        "recommendation": None,
    }

    with (
        patch("app.agent.nodes.AsyncSessionLocal", return_value=FakeSessionCtx(mock_db)),
        patch("app.agent.nodes.get_redis", return_value=fake_redis),
    ):
        await nodes.persist(state)

    assert await fake_redis.get("pending_signal:33333333-3333-3333-3333-333333333333") is None

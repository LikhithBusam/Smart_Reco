from unittest.mock import MagicMock, patch

import fakeredis.aioredis
import pytest
from fastapi import HTTPException

from app.core.rate_limit import rate_limiter


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def _fake_request(ip: str = "1.2.3.4"):
    request = MagicMock()
    request.client.host = ip
    return request


@pytest.mark.asyncio
async def test_allows_requests_under_the_limit(fake_redis):
    limiter = rate_limiter("test", max_requests=3, window_seconds=60)
    with patch("app.core.rate_limit.get_redis", return_value=fake_redis):
        for _ in range(3):
            await limiter(_fake_request())  # must not raise


@pytest.mark.asyncio
async def test_blocks_requests_over_the_limit(fake_redis):
    limiter = rate_limiter("test", max_requests=3, window_seconds=60)
    with patch("app.core.rate_limit.get_redis", return_value=fake_redis):
        for _ in range(3):
            await limiter(_fake_request())
        with pytest.raises(HTTPException) as exc_info:
            await limiter(_fake_request())

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_limits_are_tracked_per_ip_independently(fake_redis):
    limiter = rate_limiter("test", max_requests=1, window_seconds=60)
    with patch("app.core.rate_limit.get_redis", return_value=fake_redis):
        await limiter(_fake_request("1.1.1.1"))
        await limiter(_fake_request("2.2.2.2"))  # different IP, must not raise


@pytest.mark.asyncio
async def test_sets_expiry_only_on_first_request_in_window(fake_redis):
    limiter = rate_limiter("test", max_requests=5, window_seconds=60)
    with patch("app.core.rate_limit.get_redis", return_value=fake_redis):
        await limiter(_fake_request("9.9.9.9"))

    ttl = await fake_redis.ttl("ratelimit:test:9.9.9.9")
    assert 0 < ttl <= 60


@pytest.mark.asyncio
async def test_missing_client_falls_back_to_unknown_key(fake_redis):
    limiter = rate_limiter("test", max_requests=3, window_seconds=60)
    request = MagicMock()
    request.client = None

    with patch("app.core.rate_limit.get_redis", return_value=fake_redis):
        await limiter(request)  # must not raise

    assert await fake_redis.get("ratelimit:test:unknown") == "1"

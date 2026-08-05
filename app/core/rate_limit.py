from collections.abc import Callable

from fastapi import HTTPException, Request, status

from app.services.redis_client import get_redis


def rate_limiter(key_prefix: str, max_requests: int, window_seconds: int) -> Callable:
    """Cheap fixed-window counter (INCR+EXPIRE), not a true sliding-window log —
    ponytail: good enough for a hackathon abuse guard, upgrade to a sorted-set
    sliding window if precise per-second limits ever matter."""

    async def _dependency(request: Request) -> None:
        identifier = request.client.host if request.client else "unknown"
        key = f"ratelimit:{key_prefix}:{identifier}"
        redis_client = get_redis()

        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, window_seconds)

        if count > max_requests:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests")

    return _dependency


login_rate_limit = rate_limiter("login", max_requests=10, window_seconds=60)
events_rate_limit = rate_limiter("events", max_requests=100, window_seconds=60)

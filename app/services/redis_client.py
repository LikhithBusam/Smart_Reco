from functools import lru_cache

import redis.asyncio as redis

from app.config import settings

EVENTS_QUEUE_KEY = "events:pending"


@lru_cache
def get_redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)

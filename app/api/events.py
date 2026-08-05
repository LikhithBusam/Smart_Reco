import json

from fastapi import APIRouter, Depends, Response, status

from app.core.deps import get_current_user
from app.core.rate_limit import events_rate_limit
from app.db.models import User
from app.schemas.event import EventBatchRequest
from app.services.redis_client import EVENTS_QUEUE_KEY, get_redis

router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(events_rate_limit)])
async def batch_events(
    payload: EventBatchRequest,
    user: User = Depends(get_current_user),
) -> Response:
    """Pushes straight to Redis and returns immediately — no DB write and no
    LLM call on this path. See ARCHITECTURE.md §4."""
    redis_client = get_redis()
    pipe = redis_client.pipeline()
    for event in payload.events:
        record = event.model_dump(mode="json")
        record["user_id"] = str(user.id)
        pipe.lpush(EVENTS_QUEUE_KEY, json.dumps(record))
    await pipe.execute()

    return Response(status_code=status.HTTP_202_ACCEPTED)

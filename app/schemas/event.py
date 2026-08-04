from uuid import UUID

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_type: str = Field(min_length=1, max_length=50)
    entity_type: str | None = Field(default=None, max_length=50)
    entity_id: UUID | None = None
    metadata: dict | None = None
    session_id: str | None = Field(default=None, max_length=100)


class EventBatchRequest(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=50)

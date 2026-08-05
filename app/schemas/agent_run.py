from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AgentRunOut(BaseModel):
    id: UUID
    user_id: UUID
    trigger_type: str | None
    status: str
    retry_count: int
    token_usage: int | None
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}

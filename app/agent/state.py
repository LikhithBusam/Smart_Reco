from typing import TypedDict


class AgentState(TypedDict, total=False):
    user_id: str
    raw_events: list[dict]
    active_recommendation: dict | None
    should_trigger: bool
    trigger_reason: str | None
    interest_summary: str
    retrieved_products: list[dict]
    retrieval_ok: bool
    retry_count: int
    recommendation: dict | None

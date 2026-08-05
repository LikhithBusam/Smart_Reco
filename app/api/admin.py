from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.models import AgentRun, User
from app.db.session import get_db
from app.schemas.agent_run import AgentRunOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ping")
async def admin_ping(user: User = Depends(require_admin)) -> dict:
    """Proves the role-guarded dependency chain works."""
    return {"ok": True, "admin_id": str(user.id)}


@router.get("/agent-runs", response_model=list[AgentRunOut])
async def list_agent_runs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[AgentRun]:
    """Observability for judges: cache-hit efficiency is directly queryable here,
    not just in a LangSmith dashboard. See ARCHITECTURE.md §8."""
    result = await db.execute(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit))
    return list(result.scalars().all())

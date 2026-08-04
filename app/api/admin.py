from fastapi import APIRouter, Depends

from app.core.deps import require_admin
from app.db.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ping")
async def admin_ping(user: User = Depends(require_admin)) -> dict:
    """Proves the role-guarded dependency chain works. Real admin routes (products, agent-runs) land in later phases."""
    return {"ok": True, "admin_id": str(user.id)}

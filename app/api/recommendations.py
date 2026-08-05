from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import run_agent
from app.core.deps import get_current_user
from app.db.models import Product, Recommendation, User
from app.db.session import get_db
from app.schemas.product import ProductResponse
from app.schemas.recommendation import RecommendationOut

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("", response_model=RecommendationOut)
async def get_recommendations(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecommendationOut:
    # should_trigger inside the graph decides whether this actually does anything
    # (ARCHITECTURE.md §6) - safe to fire on every call, run_agent is lock-guarded too.
    background_tasks.add_task(run_agent, str(user.id))

    rec = (
        await db.execute(
            select(Recommendation).where(Recommendation.user_id == user.id, Recommendation.is_active.is_(True))
        )
    ).scalar_one_or_none()

    if rec is None:
        return RecommendationOut(narrative=None, products=[], generated_at=None)

    products = (await db.execute(select(Product).where(Product.id.in_(rec.product_ids)))).scalars().all()

    return RecommendationOut(
        narrative=rec.narrative,
        products=[ProductResponse.model_validate(p) for p in products],
        generated_at=rec.generated_at,
    )

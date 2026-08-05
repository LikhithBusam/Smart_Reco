from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_optional
from app.db.models import Product
from app.db.session import get_db

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@router.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html")


@router.get("/")
async def home_page(request: Request, q: str | None = None, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_optional(request, db)
    if user is None:
        return RedirectResponse("/login")

    query = select(Product).where(Product.is_deleted.is_(False))
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(Product.title.ilike(like), Product.description.ilike(like), Product.category.ilike(like))
        )
    products = (await db.execute(query.order_by(Product.created_at.desc()))).scalars().all()

    return templates.TemplateResponse(
        request, "home.html", {"user": user, "products": products, "query": q}
    )

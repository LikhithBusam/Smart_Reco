from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.models import Product, ProductSyncOutbox, User
from app.db.session import get_db
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate

router = APIRouter(prefix="/admin/products", tags=["admin-products"], dependencies=[Depends(require_admin)])


async def _get_product_or_404(db: AsyncSession, product_id: UUID) -> Product:
    product = (
        await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted.is_(False)))
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.get("", response_model=list[ProductResponse])
async def list_products(db: AsyncSession = Depends(get_db)) -> list[Product]:
    result = await db.execute(
        select(Product).where(Product.is_deleted.is_(False)).order_by(Product.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(payload: ProductCreate, db: AsyncSession = Depends(get_db)) -> Product:
    product = Product(**payload.model_dump())
    db.add(product)
    await db.flush()  # assigns product.id within the same transaction

    db.add(ProductSyncOutbox(product_id=product.id, operation="upsert"))
    await db.commit()
    await db.refresh(product)
    return product


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(product_id: UUID, payload: ProductUpdate, db: AsyncSession = Depends(get_db)) -> Product:
    product = await _get_product_or_404(db, product_id)

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(product, field, value)

    if updates:
        db.add(ProductSyncOutbox(product_id=product.id, operation="upsert"))

    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    product = await _get_product_or_404(db, product_id)
    product.is_deleted = True
    db.add(ProductSyncOutbox(product_id=product.id, operation="delete"))
    await db.commit()

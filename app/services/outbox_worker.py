"""Polls product_sync_outbox for pending rows and syncs Postgres -> Chroma.
One job on the shared scheduler (app/services/scheduler.py) — see
ARCHITECTURE.md §3.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import Product, ProductSyncOutbox
from app.db.session import AsyncSessionLocal
from app.vector import chroma_client

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


async def process_pending_outbox_rows() -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ProductSyncOutbox)
                .where(ProductSyncOutbox.status == "pending")
                .order_by(ProductSyncOutbox.created_at)
            )
        ).scalars().all()

        for row in rows:
            await _process_row(db, row)


async def _process_row(db, row: ProductSyncOutbox) -> None:
    try:
        if row.operation == "delete":
            chroma_client.delete_product(str(row.product_id))
        else:  # "upsert"
            product = (
                await db.execute(select(Product).where(Product.id == row.product_id))
            ).scalar_one_or_none()

            if product is None or product.is_deleted:
                chroma_client.delete_product(str(row.product_id))
            else:
                chroma_client.upsert_product(
                    product_id=str(product.id),
                    title=product.title,
                    description=product.description,
                    category=product.category,
                    price=float(product.price),
                )

        row.status = "done"
        row.processed_at = datetime.now(timezone.utc)

    except Exception:
        row.attempts += 1
        logger.exception("Outbox row %s (attempt %d) failed", row.id, row.attempts)
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
            logger.error("Outbox row %s exceeded %d attempts, marking failed", row.id, MAX_ATTEMPTS)

    await db.commit()

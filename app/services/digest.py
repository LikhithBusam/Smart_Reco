"""Daily proactive-delivery job (bonus, ARCHITECTURE.md §7). Reuses each
user's existing active recommendation - never forces a regeneration just
for the email. One job on the shared scheduler."""

import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from uuid import UUID

from sqlalchemy import select

from app.config import settings
from app.db.models import AgentRun, Event, Product, Recommendation, User
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def send_daily_digests() -> None:
    if not settings.smtp_host:
        logger.info("SMTP not configured, skipping digest run")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    async with AsyncSessionLocal() as db:
        user_ids = (
            await db.execute(select(Event.user_id).where(Event.created_at >= cutoff).distinct())
        ).scalars().all()

        for user_id in user_ids:
            await _send_one_digest(db, user_id)


async def _send_one_digest(db, user_id: UUID) -> None:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    rec = (
        await db.execute(
            select(Recommendation).where(Recommendation.user_id == user_id, Recommendation.is_active.is_(True))
        )
    ).scalar_one_or_none()

    if user is None or rec is None:
        return  # nothing to send yet, and we don't force a regen just for the email

    products = (await db.execute(select(Product).where(Product.id.in_(rec.product_ids)))).scalars().all()

    status = "completed"
    try:
        _send_email(user.email, rec.narrative, products)
    except Exception:
        logger.exception("Failed to send digest email to %s", user.email)
        status = "failed"

    db.add(
        AgentRun(
            user_id=user_id,
            trigger_type="scheduled_digest",
            status=status,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


def _send_email(to_email: str, narrative: str, products: list[Product]) -> None:
    message = EmailMessage()
    message["Subject"] = "Your SmartReco picks for today"
    message["From"] = settings.smtp_user or "smartreco@example.com"
    message["To"] = to_email
    message.set_content(narrative)
    message.add_alternative(_render_html(narrative, products), subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def _render_html(narrative: str, products: list[Product]) -> str:
    cards = "".join(
        f'<div style="border:1px solid #ddd;border-radius:8px;padding:.75rem;margin:.5rem 0;">'
        f"<strong>{escape(p.title)}</strong><br>"
        f'<span style="color:#555;">{escape(p.category)} &middot; ${p.price}</span>'
        f"</div>"
        for p in products
    )
    return (
        '<div style="font-family: system-ui, sans-serif; max-width: 480px;">'
        "<h2>Your SmartReco picks for today</h2>"
        f"<p>{escape(narrative)}</p>"
        f"{cards}"
        "</div>"
    )

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services import digest
from tests.conftest import FakeSessionCtx, make_mock_db


def _db_with(user, rec, products) -> MagicMock:
    db = make_mock_db()
    events_result = MagicMock()
    events_result.scalars.return_value.all.return_value = [user.id] if user else []
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    rec_result = MagicMock()
    rec_result.scalar_one_or_none.return_value = rec
    products_result = MagicMock()
    products_result.scalars.return_value.all.return_value = products
    db.execute.side_effect = [events_result, user_result, rec_result, products_result]
    return db


@pytest.mark.asyncio
async def test_send_daily_digests_noop_when_smtp_not_configured(monkeypatch):
    monkeypatch.setattr(digest.settings, "smtp_host", "")
    with patch("app.services.digest.AsyncSessionLocal") as mock_session:
        await digest.send_daily_digests()
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_skips_user_with_no_active_recommendation(monkeypatch):
    monkeypatch.setattr(digest.settings, "smtp_host", "smtp.example.com")
    user = MagicMock(id=uuid4(), email="u@example.com")
    db = _db_with(user, rec=None, products=[])

    with (
        patch("app.services.digest.AsyncSessionLocal", return_value=FakeSessionCtx(db)),
        patch("app.services.digest._send_email") as mock_send,
    ):
        await digest.send_daily_digests()

    mock_send.assert_not_called()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_sends_email_and_logs_agent_run_when_recommendation_exists(monkeypatch):
    monkeypatch.setattr(digest.settings, "smtp_host", "smtp.example.com")
    user = MagicMock(id=uuid4(), email="u@example.com")
    rec = MagicMock(narrative="You'll like these", product_ids=[uuid4()])
    product = MagicMock(title="Agentic AI", category="ai", price=Decimal("49.00"))
    db = _db_with(user, rec, [product])

    with (
        patch("app.services.digest.AsyncSessionLocal", return_value=FakeSessionCtx(db)),
        patch("app.services.digest._send_email") as mock_send,
    ):
        await digest.send_daily_digests()

    mock_send.assert_called_once_with("u@example.com", "You'll like these", [product])
    logged_run = next(c.args[0] for c in db.add.call_args_list)
    assert logged_run.trigger_type == "scheduled_digest"
    assert logged_run.status == "completed"


@pytest.mark.asyncio
async def test_logs_failed_status_when_smtp_send_raises(monkeypatch):
    monkeypatch.setattr(digest.settings, "smtp_host", "smtp.example.com")
    user = MagicMock(id=uuid4(), email="u@example.com")
    rec = MagicMock(narrative="n", product_ids=[])
    db = _db_with(user, rec, [])

    with (
        patch("app.services.digest.AsyncSessionLocal", return_value=FakeSessionCtx(db)),
        patch("app.services.digest._send_email", side_effect=OSError("connection refused")),
    ):
        await digest.send_daily_digests()

    logged_run = next(c.args[0] for c in db.add.call_args_list)
    assert logged_run.status == "failed"


def test_render_html_escapes_narrative_and_product_fields():
    product = MagicMock(title="<script>alert(1)</script>", category="ai", price=Decimal("1.00"))
    html = digest._render_html("<b>hi</b>", [product])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_send_email_uses_starttls_and_configured_credentials(monkeypatch):
    monkeypatch.setattr(digest.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(digest.settings, "smtp_port", 587)
    monkeypatch.setattr(digest.settings, "smtp_user", "bot@example.com")
    monkeypatch.setattr(digest.settings, "smtp_password", "secret")

    mock_smtp_instance = MagicMock()
    mock_smtp_cls = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_smtp_instance

    with patch("app.services.digest.smtplib.SMTP", mock_smtp_cls):
        digest._send_email("to@example.com", "narrative", [])

    mock_smtp_instance.starttls.assert_called_once()
    mock_smtp_instance.login.assert_called_once_with("bot@example.com", "secret")
    mock_smtp_instance.send_message.assert_called_once()

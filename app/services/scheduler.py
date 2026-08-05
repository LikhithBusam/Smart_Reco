"""Single APScheduler instance for every background job in this app:
outbox flush, event consumer, daily digest email — see ARCHITECTURE.md §11.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.services.digest import send_daily_digests
from app.services.event_consumer import consume_pending_events
from app.services.outbox_worker import process_pending_outbox_rows

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    scheduler.add_job(
        process_pending_outbox_rows,
        trigger="interval",
        seconds=settings.outbox_poll_interval_seconds,
        id="outbox_worker",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        consume_pending_events,
        trigger="interval",
        seconds=settings.event_consumer_poll_interval_seconds,
        id="event_consumer",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        send_daily_digests,
        trigger="cron",
        hour=settings.digest_send_hour_utc,
        minute=0,
        id="daily_digest",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("Scheduler started with jobs: %s", [job.id for job in scheduler.get_jobs()])


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)

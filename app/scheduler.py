"""Scheduler module for MedNews Secretary Agent.

APScheduler-based async scheduler for digest and reminder jobs.
Provides build_scheduler(), run_digest_job(), and run_reminder_job().
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from structlog.contextvars import bind_contextvars

from app.config import Settings, get_settings
from app.logging_setup import get_logger, new_request_id
from app.services.digest_builder import build_digest_message, send_digest_to_telegram
from app.services.reminder_engine import ReminderEngine

# Graceful shutdown timeout in seconds
MISFIRE_GRACE_TIME = 300


def build_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    """Build and configure AsyncIOScheduler with digest and reminder jobs.

    Creates an AsyncIOScheduler instance with exactly two jobs:
    - "digest": Daily cron job at DIGEST_HOUR:DIGEST_MINUTE in user's TIMEZONE
    - "reminder": Interval job every REMINDER_POLL_INTERVAL_MINUTES

    Args:
        settings: Application settings. If None, retrieves via get_settings().

    Returns:
        Configured AsyncIOScheduler instance (NOT started).
        Caller must call scheduler.start() and scheduler.shutdown(wait=True) for graceful shutdown.

    Raises:
        ValueError: If TELEGRAM_DIGEST_CHAT_ID is not configured.
    """
    if settings is None:
        settings = get_settings()

    logger = get_logger("scheduler")
    scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)

    # Digest job: daily at DIGEST_HOUR:DIGEST_MINUTE
    digest_trigger = CronTrigger(
        hour=settings.DIGEST_HOUR,
        minute=settings.DIGEST_MINUTE,
        timezone=settings.TIMEZONE,
    )
    scheduler.add_job(
        func=run_digest_job,
        trigger=digest_trigger,
        id="digest",
        name="Daily medical digest",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )
    logger.info(
        "Digest job configured",
        extra={
            "hour": settings.DIGEST_HOUR,
            "minute": settings.DIGEST_MINUTE,
            "timezone": str(settings.TIMEZONE),
        },
    )

    # Reminder job: interval polling
    reminder_trigger = IntervalTrigger(
        minutes=settings.REMINDER_POLL_INTERVAL_MINUTES,
    )
    scheduler.add_job(
        func=run_reminder_job,
        trigger=reminder_trigger,
        id="reminder",
        name="Reminder poll",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )
    logger.info(
        "Reminder job configured",
        extra={"interval_minutes": settings.REMINDER_POLL_INTERVAL_MINUTES},
    )

    return scheduler


async def run_digest_job() -> None:
    """Execute daily digest job: build and send digest message.

    Pipeline:
    1. Bind new request_id to context
    2. Build digest message via build_digest_message()
    3. If digest is non-empty: send to TELEGRAM_DIGEST_CHAT_ID
    4. Log errors and notify admin on failure (does NOT propagate exceptions)

    Exceptions are caught, logged, and admin is notified via TELEGRAM_ADMIN_ID.
    """
    request_id = new_request_id()
    bind_contextvars(request_id=request_id)
    logger = get_logger("scheduler")

    logger.info("Starting digest job", extra={"request_id": request_id})

    settings = get_settings()

    try:
        # Build digest message
        digest_message = await build_digest_message(
            lookback_hours=settings.NEWS_LOOKBACK_HOURS
        )

        # Only send if non-empty
        if digest_message:
            await send_digest_to_telegram(
                chat_id=settings.TELEGRAM_DIGEST_CHAT_ID, message=digest_message
            )
            logger.info(
                "Digest sent successfully",
                extra={"request_id": request_id, "message_length": len(digest_message)},
            )
        else:
            logger.info(
                "No digest to send (empty)",
                extra={"request_id": request_id},
            )

    except Exception as e:
        logger.error(
            "Digest job failed",
            extra={"request_id": request_id, "error": str(e)},
        )

        # Notify admin
        if settings.TELEGRAM_ADMIN_ID:
            try:
                from aiogram import Bot

                bot = Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())
                await bot.send_message(
                    chat_id=settings.TELEGRAM_ADMIN_ID,
                    text=f"CRITICAL: Digest job failed: {e}",
                    parse_mode=None,
                )
                await bot.close()
                logger.info(
                    "Admin notification sent",
                    extra={"request_id": request_id},
                )
            except Exception as notify_error:
                logger.warning(
                    "Failed to notify admin about digest failure",
                    extra={"request_id": request_id, "error": str(notify_error)},
                )


async def run_reminder_job() -> None:
    """Execute reminder job: poll upcoming events and send reminders.

    Calls ReminderEngine.poll_and_remind() to check for events in the
    reminder window and send proactive notifications.

    Exceptions are caught and logged (does NOT propagate exceptions).
    """
    request_id = new_request_id()
    bind_contextvars(request_id=request_id)
    logger = get_logger("scheduler")

    logger.info("Starting reminder job", extra={"request_id": request_id})

    try:
        engine = ReminderEngine()
        sent_count = await engine.poll_and_remind()
        logger.info(
            "Reminder job completed",
            extra={"request_id": request_id, "reminders_sent": sent_count},
        )

    except Exception as e:
        logger.error(
            "Reminder job failed",
            extra={"request_id": request_id, "error": str(e)},
        )

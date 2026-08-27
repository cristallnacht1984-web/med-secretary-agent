"""Reminder Engine: polls upcoming events and sends proactive reminders."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.config import Settings, get_settings
from app.db.database import get_session
from app.db.repository import Repository
from app.llm.client import LLMClient
from app.llm.schemas import ReminderSummary
from app.logging_setup import get_logger, new_request_id
from app.services.calendar_service import CalendarAPIError, CalendarAuthError, CalendarService

REMINDER_WINDOW_MIN_MIN = 30
REMINDER_WINDOW_MAX_MIN = 60
POLL_HORIZON_HOURS = 2
TG_RETRY_ATTEMPTS = 3
TG_RETRY_BASE_DELAY = 1.0


def _utcnow() -> datetime:
    """Module-level clock for testing. Returns current UTC time as aware datetime."""
    return datetime.now(UTC)


def _escape_md_v2(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters.
    
    Args:
        text: Raw text to escape.
        
    Returns:
        Text with special characters escaped by backslash.
    """
    special_chars = r"_*[]()~`#+\-=|{}.!"
    return re.sub(rf"([{re.escape(special_chars)}])", r"\\\1", text)


class ReminderEngine:
    """Движок напоминаний: полл событий → LLM summary → TG сообщение."""

    def __init__(self, settings: Settings | None = None):
        """Initialize ReminderEngine with optional Settings.
        
        Args:
            settings: Application settings. If None, uses get_settings().
        """
        self.settings = settings if settings is not None else get_settings()
        self.calendar_service = CalendarService(self.settings)
        self.llm_client = LLMClient(self.settings)
        self.bot = Bot(token=self.settings.TELEGRAM_BOT_TOKEN.get_secret_value())
        self.logger = get_logger("reminder_engine")

    async def poll_and_remind(self) -> int:
        """Main loop: find events in next 2 hours → create reminders.
        
        Returns:
            Number of successfully sent and marked reminders.
        """
        request_id = new_request_id()
        bind_contextvars(request_id=request_id)
        self.logger.info(
            "Starting reminder poll",
            extra={"request_id": request_id},
        )
        
        now = _utcnow()
        horizon = now + timedelta(hours=POLL_HORIZON_HOURS)
        
        # Получить события
        try:
            events = await self.calendar_service.get_upcoming_events(now, horizon)
        except (CalendarAuthError, CalendarAPIError) as e:
            self.logger.error(
                "Calendar error during poll",
                extra={"request_id": request_id, "error": str(e)},
            )
            return 0
        
        sent_count = 0
        total_events = len(events)
        
        try:
            for event in events:
                event_id = event["id"]
                event_start = event["start_time"]
                
                # Проверить окно напоминаний
                if not await self._should_send_reminder(event_start):
                    continue
                
                # Дедупликация
                user_id = self.settings.TELEGRAM_ADMIN_ID
                if user_id is None:
                    self.logger.warning(
                        "TELEGRAM_ADMIN_ID not set, skipping reminder",
                        extra={"request_id": request_id, "event_id": event_id},
                    )
                    continue
                
                async for session in get_session():
                    repo = Repository(session)
                    if await repo.was_reminder_sent(event_id, user_id):
                        self.logger.debug(
                            "Reminder already sent",
                            extra={"request_id": request_id, "event_id": event_id},
                        )
                        continue
                    
                    # LLM summary
                    try:
                        summary = await self.llm_client.summarize_reminder(event)
                    except Exception as e:
                        self.logger.warning(
                            "LLM error for event",
                            extra={"request_id": request_id, "event_id": event_id, "error": str(e)},
                        )
                        continue
                    
                    # Отправить в Telegram
                    message_text = self._format_reminder_message(summary)
                    message_id = await self._send_telegram_with_retry(message_text, request_id)
                    
                    if message_id is None:
                        # Все попытки провалились
                        self.logger.error(
                            "Failed to send reminder after retries",
                            extra={"request_id": request_id, "event_id": event_id},
                        )
                        continue
                    
                    # Отметить как отправленное
                    await repo.mark_reminder_sent(event_id, event_start, user_id)
                    sent_count += 1
                    
                    self.logger.info(
                        "Reminder sent successfully",
                        extra={
                            "request_id": request_id,
                            "event_id": event_id,
                            "message_id": message_id,
                        },
                    )
        finally:
            clear_contextvars()
        
        self.logger.info(
            "Reminder poll completed",
            extra={
                "request_id": request_id,
                "sent_count": sent_count,
                "total_events": total_events,
            },
        )
        return sent_count

    async def _should_send_reminder(self, event_start: datetime) -> bool:
        """Check if event is within 30-60 minute reminder window.
        
        Args:
            event_start: Event start time (aware UTC datetime).
            
        Returns:
            True if now + 30min <= event_start <= now + 60min (inclusive).
        """
        now = _utcnow()
        min_threshold = now + timedelta(minutes=REMINDER_WINDOW_MIN_MIN)
        max_threshold = now + timedelta(minutes=REMINDER_WINDOW_MAX_MIN)
        return min_threshold <= event_start <= max_threshold

    def _format_reminder_message(self, summary: ReminderSummary) -> str:
        """Format ReminderSummary into Telegram MarkdownV2 message.
        
        Args:
            summary: ReminderSummary from LLM client.
            
        Returns:
            Formatted message string with escaped special characters.
        """
        # Конвертировать event_start в user TZ для отображения
        user_tz = ZoneInfo(str(self.settings.TIMEZONE))
        event_start_local = summary.event_start.astimezone(user_tz)
        time_str = event_start_local.strftime("%H:%M")
        
        lines = [
            f"📅 *{_escape_md_v2(summary.event_title)}*",
            f"🕐 {_escape_md_v2(time_str)}",
            "",
            _escape_md_v2(summary.summary),
        ]
        
        if summary.preparation_tips:
            lines.append("")
            for tip in summary.preparation_tips:
                lines.append(f"💡 {_escape_md_v2(tip)}")
        
        return "\n".join(lines)

    async def _send_telegram_with_retry(self, message: str, request_id: str) -> int | None:
        """Send message to Telegram with exponential backoff retry.
        
        Args:
            message: Message text in MarkdownV2 format.
            request_id: Request ID for logging.
            
        Returns:
            message_id on success, None on failure after all attempts.
        """
        chat_id = self.settings.TELEGRAM_ADMIN_ID
        if chat_id is None:
            return None
        
        last_exception: Exception | None = None
        for attempt in range(TG_RETRY_ATTEMPTS):
            try:
                response = await self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="MarkdownV2",
                )
                return response.message_id
            except TelegramAPIError as e:
                last_exception = e
                if attempt < TG_RETRY_ATTEMPTS - 1:
                    delay = TG_RETRY_BASE_DELAY * (2 ** attempt)
                    self.logger.warning(
                        f"Telegram send failed (attempt {attempt + 1}/{TG_RETRY_ATTEMPTS})",
                        extra={"request_id": request_id, "error": str(e), "retry_delay": delay},
                    )
                    await asyncio.sleep(delay)
            except Exception as e:
                last_exception = e
                if attempt < TG_RETRY_ATTEMPTS - 1:
                    delay = TG_RETRY_BASE_DELAY * (2 ** attempt)
                    self.logger.warning(
                        f"Telegram send failed (attempt {attempt + 1}/{TG_RETRY_ATTEMPTS})",
                        extra={"request_id": request_id, "error": str(e), "retry_delay": delay},
                    )
                    await asyncio.sleep(delay)
        
        self.logger.error(
            f"Telegram send failed after {TG_RETRY_ATTEMPTS} attempts",
            extra={"request_id": request_id, "last_error": str(last_exception)},
        )
        return None

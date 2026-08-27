"""Tests for reminder_engine module."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError

from app.config import get_settings
from app.llm.schemas import ReminderSummary
from app.services.calendar_service import CalendarAPIError, CalendarAuthError
from app.services.reminder_engine import (
    REMINDER_WINDOW_MAX_MIN,
    REMINDER_WINDOW_MIN_MIN,
    ReminderEngine,
    _escape_md_v2,
)


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch: pytest.MonkeyPatch):
    """Clean environment variables and clear settings cache before each test."""
    env_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_DIGEST_CHAT_ID",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
        "LLM_TEMPERATURE_ANALYSIS",
        "LLM_TEMPERATURE_CLASSIFICATION",
        "LLM_TEMPERATURE_REMINDER",
        "LLM_MAX_TOKENS",
        "LLM_TIMEOUT_ANALYSIS",
        "LLM_TIMEOUT_CLASSIFICATION",
        "LLM_TIMEOUT_REMINDER",
        "LLM_RATE_LIMIT_RPM",
        "LLM_RATE_LIMIT_TPM",
        "LLM_MAX_RETRIES",
        "DATABASE_URL",
        "GOOGLE_CREDENTIALS_JSON",
        "GOOGLE_CREDENTIALS_FILE",
        "GOOGLE_TOKEN_FILE",
        "GOOGLE_CALENDAR_ID",
        "DIGEST_TIME_HOUR",
        "DIGEST_HOUR",
        "DIGEST_MINUTE",
        "REMINDER_POLL_INTERVAL_MINUTES",
        "REMINDER_WINDOW_HOURS",
        "REMINDER_LOOKAHEAD_MINUTES",
        "HEALTH_CHECK_HOST",
        "HEALTH_CHECK_PORT",
        "USER_TIMEZONE",
        "TIMEZONE",
        "LOG_LEVEL",
        "LOG_FILE",
        "NEWS_LOOKBACK_HOURS",
        "NEWS_DEDUP_WINDOW_DAYS",
        "NEWS_BATCH_MIN",
        "NEWS_BATCH_MAX",
        "NEWS_DELIVERY_RETRIES",
        "NEWS_DELIVERY_RETRY_DELAY_MINUTES",
        "FETCH_TIMEOUT_SECONDS",
        "FETCH_MAX_RETRIES",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)

    # Set required values with valid formats
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "42:TEST_TOKEN")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456")
    monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
    monkeypatch.setenv("TIMEZONE", "Europe/Moscow")

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def create_mock_event(event_id: str, start_offset_minutes: int) -> dict:
    """Create a mock event dict."""
    now = datetime.now(UTC)
    return {
        "id": event_id,
        "title": f"Event {event_id}",
        "start_time": now + timedelta(minutes=start_offset_minutes),
        "end_time": now + timedelta(minutes=start_offset_minutes + 60),
        "description": f"Description for {event_id}",
        "location": "Location",
    }


class TestPollAndRemindNoEvents:
    """Test poll_and_remind with no events."""

    @pytest.mark.asyncio
    async def test_zero_events_returns_zero(self):
        """0 событий → return 0; LLM/TG/repository не вызывались."""
        engine = ReminderEngine()
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.return_value = []
        engine.calendar_service = mock_calendar
        
        mock_llm = AsyncMock()
        engine.llm_client = mock_llm
        
        mock_bot = AsyncMock()
        engine.bot = mock_bot
        
        result = await engine.poll_and_remind()
        
        assert result == 0
        mock_llm.summarize_reminder.assert_not_called()
        mock_bot.send_message.assert_not_called()


class TestPollAndRemindSingleEventInWindow:
    """Test poll_and_remind with one event in window."""

    @pytest.mark.asyncio
    async def test_one_event_in_window_sends_reminder(self):
        """1 событие в окне 30–60 мин → summarize + send_message + mark_reminder_sent, return 1."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        event_start = now + timedelta(minutes=45)
        mock_event = {
            "id": "evt_001",
            "title": "Meeting",
            "start_time": event_start,
            "end_time": event_start + timedelta(hours=1),
            "description": "Team meeting",
            "location": "Office",
        }
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.return_value = [mock_event]
        engine.calendar_service = mock_calendar
        
        mock_summary = ReminderSummary(
            event_title="Meeting",
            event_start=event_start,
            summary="Team sync meeting",
            preparation_tips=["Prepare agenda", "Check calendar"],
        )
        mock_llm = AsyncMock()
        mock_llm.summarize_reminder.return_value = mock_summary
        engine.llm_client = mock_llm
        
        mock_repo_instance = AsyncMock()
        mock_repo_instance.was_reminder_sent.return_value = False
        mock_repo_instance.mark_reminder_sent = AsyncMock()
        
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        mock_bot = AsyncMock()
        mock_bot.send_message.return_value = MagicMock(message_id=123)
        engine.bot = mock_bot
        
        async def mock_get_session_gen():
            yield mock_session
        
        with patch("app.services.reminder_engine.get_session", side_effect=mock_get_session_gen), \
             patch("app.services.reminder_engine.Repository", return_value=mock_repo_instance):
            result = await engine.poll_and_remind()
        
        assert result == 1
        mock_llm.summarize_reminder.assert_called_once_with(mock_event)
        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args[1]
        assert call_kwargs["parse_mode"] == "MarkdownV2"
        mock_repo_instance.mark_reminder_sent.assert_called_once()


class TestPollAndRemindEventOutsideWindow:
    """Test poll_and_remind with events outside window."""

    @pytest.mark.asyncio
    async def test_event_less_than_30_min_skipped(self):
        """Событие < 30 мин → skip, LLM/TG не вызываются."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        mock_event = {
            "id": "evt_001",
            "title": "Soon Meeting",
            "start_time": now + timedelta(minutes=15),
            "end_time": now + timedelta(minutes=75),
            "description": "Too soon",
            "location": "Office",
        }
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.return_value = [mock_event]
        engine.calendar_service = mock_calendar
        
        mock_llm = AsyncMock()
        engine.llm_client = mock_llm
        
        mock_bot = AsyncMock()
        engine.bot = mock_bot
        
        result = await engine.poll_and_remind()
        
        assert result == 0
        mock_llm.summarize_reminder.assert_not_called()
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_more_than_60_min_skipped(self):
        """Событие > 60 мин → skip, LLM/TG не вызываются."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        mock_event = {
            "id": "evt_001",
            "title": "Later Meeting",
            "start_time": now + timedelta(minutes=90),
            "end_time": now + timedelta(minutes=150),
            "description": "Too late",
            "location": "Office",
        }
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.return_value = [mock_event]
        engine.calendar_service = mock_calendar
        
        mock_llm = AsyncMock()
        engine.llm_client = mock_llm
        
        mock_bot = AsyncMock()
        engine.bot = mock_bot
        
        result = await engine.poll_and_remind()
        
        assert result == 0
        mock_llm.summarize_reminder.assert_not_called()
        mock_bot.send_message.assert_not_called()


class TestPollAndRemindMultipleEvents:
    """Test poll_and_remind with multiple events."""

    @pytest.mark.asyncio
    async def test_three_events_in_window_three_reminders(self):
        """3 события в окне → 3 отправки, return 3."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        events = [
            {
                "id": f"evt_{i:03d}",
                "title": f"Event {i}",
                "start_time": now + timedelta(minutes=40 + i * 5),
                "end_time": now + timedelta(minutes=100 + i * 5),
                "description": f"Desc {i}",
                "location": "Office",
            }
            for i in range(3)
        ]
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.return_value = events
        engine.calendar_service = mock_calendar
        
        mock_summary = ReminderSummary(
            event_title="Event",
            event_start=now,
            summary="Summary",
            preparation_tips=["Tip"],
        )
        mock_llm = AsyncMock()
        mock_llm.summarize_reminder.return_value = mock_summary
        engine.llm_client = mock_llm
        
        mock_repo_instance = AsyncMock()
        mock_repo_instance.was_reminder_sent.return_value = False
        mock_repo_instance.mark_reminder_sent = AsyncMock()
        
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        mock_bot = AsyncMock()
        mock_bot.send_message.return_value = MagicMock(message_id=123)
        engine.bot = mock_bot
        
        async def mock_get_session_gen():
            yield mock_session
        
        with patch("app.services.reminder_engine.get_session", side_effect=mock_get_session_gen), \
             patch("app.services.reminder_engine.Repository", return_value=mock_repo_instance):
            result = await engine.poll_and_remind()
        
        assert result == 3
        assert mock_llm.summarize_reminder.call_count == 3
        assert mock_bot.send_message.call_count == 3
        assert mock_repo_instance.mark_reminder_sent.call_count == 3


class TestPollAndRemindDeduplication:
    """Test deduplication via was_reminder_sent."""

    @pytest.mark.asyncio
    async def test_was_reminder_sent_true_skips_event(self):
        """was_reminder_sent=True → skip (дедупликация)."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        mock_event = {
            "id": "evt_001",
            "title": "Meeting",
            "start_time": now + timedelta(minutes=45),
            "end_time": now + timedelta(minutes=105),
            "description": "Already reminded",
            "location": "Office",
        }
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.return_value = [mock_event]
        engine.calendar_service = mock_calendar
        
        mock_llm = AsyncMock()
        engine.llm_client = mock_llm
        
        mock_bot = AsyncMock()
        engine.bot = mock_bot
        
        mock_repo_instance = AsyncMock()
        mock_repo_instance.was_reminder_sent.return_value = True
        
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        async def mock_get_session_gen():
            yield mock_session
        
        with patch("app.services.reminder_engine.get_session", side_effect=mock_get_session_gen), \
             patch("app.services.reminder_engine.Repository", return_value=mock_repo_instance):
            result = await engine.poll_and_remind()
        
        assert result == 0
        mock_llm.summarize_reminder.assert_not_called()
        mock_bot.send_message.assert_not_called()


class TestPollAndRemindCalendarErrors:
    """Test calendar service errors."""

    @pytest.mark.asyncio
    async def test_calendar_auth_error_returns_zero(self):
        """CalendarAuthError → return 0, log error."""
        engine = ReminderEngine()
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.side_effect = CalendarAuthError("Auth failed")
        engine.calendar_service = mock_calendar
        
        result = await engine.poll_and_remind()
        
        assert result == 0

    @pytest.mark.asyncio
    async def test_calendar_api_error_returns_zero(self):
        """CalendarAPIError → return 0, log error."""
        engine = ReminderEngine()
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.side_effect = CalendarAPIError("API failed")
        engine.calendar_service = mock_calendar
        
        result = await engine.poll_and_remind()
        
        assert result == 0


class TestPollAndRemindLLMError:
    """Test LLM errors during processing."""

    @pytest.mark.asyncio
    async def test_llm_error_on_one_event_processes_others(self):
        """LLM-ошибка на 1 из 2 → второе обработано."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        events = [
            {
                "id": "evt_001",
                "title": "Event 1",
                "start_time": now + timedelta(minutes=40),
                "end_time": now + timedelta(minutes=100),
                "description": "First",
                "location": "Office",
            },
            {
                "id": "evt_002",
                "title": "Event 2",
                "start_time": now + timedelta(minutes=50),
                "end_time": now + timedelta(minutes=110),
                "description": "Second",
                "location": "Office",
            },
        ]
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.return_value = events
        engine.calendar_service = mock_calendar
        
        mock_llm = AsyncMock()
        mock_llm.summarize_reminder.side_effect = [
            Exception("LLM error"),
            ReminderSummary(
                event_title="Event 2",
                event_start=events[1]["start_time"],
                summary="Summary 2",
                preparation_tips=["Tip"],
            ),
        ]
        engine.llm_client = mock_llm
        
        mock_repo_instance = AsyncMock()
        mock_repo_instance.was_reminder_sent.return_value = False
        mock_repo_instance.mark_reminder_sent = AsyncMock()
        
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        mock_bot = AsyncMock()
        mock_bot.send_message.return_value = MagicMock(message_id=123)
        engine.bot = mock_bot
        
        async def mock_get_session_gen():
            yield mock_session
        
        with patch("app.services.reminder_engine.get_session", side_effect=mock_get_session_gen), \
             patch("app.services.reminder_engine.Repository", return_value=mock_repo_instance):
            result = await engine.poll_and_remind()
        
        assert result == 1
        assert mock_bot.send_message.call_count == 1


class TestPollAndRemindTelegramRetryFailure:
    """Test Telegram send failure after all retries."""

    @pytest.mark.asyncio
    async def test_telegram_all_retries_fail_no_mark_sent(self):
        """TG упал все 3 попытки → mark_reminder_sent НЕ вызван."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        mock_event = {
            "id": "evt_001",
            "title": "Meeting",
            "start_time": now + timedelta(minutes=45),
            "end_time": now + timedelta(minutes=105),
            "description": "Test",
            "location": "Office",
        }
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.return_value = [mock_event]
        engine.calendar_service = mock_calendar
        
        mock_summary = ReminderSummary(
            event_title="Meeting",
            event_start=mock_event["start_time"],
            summary="Summary",
            preparation_tips=["Tip"],
        )
        mock_llm = AsyncMock()
        mock_llm.summarize_reminder.return_value = mock_summary
        engine.llm_client = mock_llm
        
        mock_repo_instance = AsyncMock()
        mock_repo_instance.was_reminder_sent.return_value = False
        mock_repo_instance.mark_reminder_sent = AsyncMock()
        
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = TelegramAPIError("Send failed", "send_message")
        engine.bot = mock_bot
        
        async def mock_get_session_gen():
            yield mock_session
        
        with patch("app.services.reminder_engine.get_session", side_effect=mock_get_session_gen), \
             patch("app.services.reminder_engine.Repository", return_value=mock_repo_instance):
            result = await engine.poll_and_remind()
        
        assert result == 0
        mock_repo_instance.mark_reminder_sent.assert_not_called()


class TestShouldSendReminderBoundaries:
    """Test _should_send_reminder boundary conditions."""

    @pytest.mark.asyncio
    async def test_exactly_30_minutes_true(self):
        """_should_send_reminder: ровно +30 мин → True (граница)."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        event_start = now + timedelta(minutes=REMINDER_WINDOW_MIN_MIN)
        
        with patch("app.services.reminder_engine._utcnow", return_value=now):
            result = await engine._should_send_reminder(event_start)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_exactly_60_minutes_true(self):
        """_should_send_reminder: ровно +60 мин → True (граница)."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        event_start = now + timedelta(minutes=REMINDER_WINDOW_MAX_MIN)
        
        with patch("app.services.reminder_engine._utcnow", return_value=now):
            result = await engine._should_send_reminder(event_start)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_29_minutes_false(self):
        """_should_send_reminder: +29 мин → False."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        event_start = now + timedelta(minutes=29)
        
        with patch("app.services.reminder_engine._utcnow", return_value=now):
            result = await engine._should_send_reminder(event_start)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_61_minutes_false(self):
        """_should_send_reminder: +61 мин → False."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        event_start = now + timedelta(minutes=61)
        
        with patch("app.services.reminder_engine._utcnow", return_value=now):
            result = await engine._should_send_reminder(event_start)
        
        assert result is False


class TestFormatReminderMessage:
    """Test _format_reminder_message formatting."""

    def test_full_summary_with_tips(self):
        """_format_reminder_message: есть 📅, 🕐, 💡, *заголовок*."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        summary = ReminderSummary(
            event_title="Team Meeting",
            event_start=now,
            summary="Discuss project progress",
            preparation_tips=["Prepare report", "Check emails"],
        )
        
        message = engine._format_reminder_message(summary)
        
        assert "📅" in message
        assert "🕐" in message
        assert "💡" in message
        assert "*Team Meeting*" in message
        assert "Prepare report" in message
        assert "Check emails" in message

    def test_empty_preparation_tips_no_tips_block(self):
        """_format_reminder_message: пустой preparation_tips → нет 💡."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        summary = ReminderSummary(
            event_title="Simple Event",
            event_start=now,
            summary="Just an event",
            preparation_tips=None,
        )
        
        message = engine._format_reminder_message(summary)
        
        assert "💡" not in message

    def test_special_characters_escaped(self):
        """_format_reminder_message: спецсимволы `_ * [ ] ( ) . !` экранированы `\\`."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        summary = ReminderSummary(
            event_title="Test_Event *with* [special] (chars) .and! more",
            event_start=now,
            summary="Summary with _underscore_ and *asterisk*",
            preparation_tips=["Tip with - dash", "Tip with = equals"],
        )
        
        message = engine._format_reminder_message(summary)
        
        # Check escaping
        assert "\\_" in message
        assert "\\*" in message
        assert "\\[" in message
        assert "\\]" in message
        assert "\\(" in message
        assert "\\)" in message
        assert "\\." in message
        assert "\\!" in message


class TestRequestIDBinding:
    """Test request_id binding in poll_and_remind."""

    @pytest.mark.asyncio
    async def test_poll_and_remind_binds_request_id(self):
        """poll_and_remind вызывает new_request_id + bind_contextvars(request_id=...)."""
        
        with patch("app.services.reminder_engine.new_request_id", return_value="test_req_123") as mock_new_id, \
             patch("app.services.reminder_engine.bind_contextvars") as mock_bind:
            engine = ReminderEngine()
            
            mock_calendar = AsyncMock()
            mock_calendar.get_upcoming_events.return_value = []
            engine.calendar_service = mock_calendar
            
            await engine.poll_and_remind()
            
            mock_new_id.assert_called_once()
            mock_bind.assert_called_once_with(request_id="test_req_123")


class TestIntegrationTwoEventsOneAlreadySent:
    """Integration test: full flow with two events, one already sent."""

    @pytest.mark.asyncio
    async def test_two_events_one_already_sent_exactly_one_reminder(self):
        """Integration: 2 события, одно уже отправлено → ровно 1."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        events = [
            {
                "id": "evt_001",
                "title": "Event 1",
                "start_time": now + timedelta(minutes=40),
                "end_time": now + timedelta(minutes=100),
                "description": "First",
                "location": "Office",
            },
            {
                "id": "evt_002",
                "title": "Event 2",
                "start_time": now + timedelta(minutes=50),
                "end_time": now + timedelta(minutes=110),
                "description": "Second",
                "location": "Office",
            },
        ]
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.return_value = events
        engine.calendar_service = mock_calendar
        
        mock_summary = ReminderSummary(
            event_title="Event",
            event_start=now,
            summary="Summary",
            preparation_tips=["Tip"],
        )
        mock_llm = AsyncMock()
        mock_llm.summarize_reminder.return_value = mock_summary
        engine.llm_client = mock_llm
        
        mock_repo_instance = AsyncMock()
        mock_repo_instance.was_reminder_sent.side_effect = [True, False]  # First sent, second not
        mock_repo_instance.mark_reminder_sent = AsyncMock()
        
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        mock_bot = AsyncMock()
        mock_bot.send_message.return_value = MagicMock(message_id=123)
        engine.bot = mock_bot
        
        async def mock_get_session_gen():
            yield mock_session
        
        with patch("app.services.reminder_engine.get_session", side_effect=mock_get_session_gen), \
             patch("app.services.reminder_engine.Repository", return_value=mock_repo_instance):
            result = await engine.poll_and_remind()
        
        assert result == 1
        assert mock_bot.send_message.call_count == 1
        assert mock_repo_instance.mark_reminder_sent.call_count == 1


class TestTelegramRetrySuccess:
    """Test Telegram retry with eventual success."""

    @pytest.mark.asyncio
    async def test_retry_first_fail_second_success_marks_sent(self):
        """Retry: 1-я попытка TelegramAPIError, 2-я успех → mark_reminder_sent вызван."""
        engine = ReminderEngine()
        
        now = datetime.now(UTC)
        mock_event = {
            "id": "evt_001",
            "title": "Meeting",
            "start_time": now + timedelta(minutes=45),
            "end_time": now + timedelta(minutes=105),
            "description": "Test",
            "location": "Office",
        }
        
        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events.return_value = [mock_event]
        engine.calendar_service = mock_calendar
        
        mock_summary = ReminderSummary(
            event_title="Meeting",
            event_start=mock_event["start_time"],
            summary="Summary",
            preparation_tips=["Tip"],
        )
        mock_llm = AsyncMock()
        mock_llm.summarize_reminder.return_value = mock_summary
        engine.llm_client = mock_llm
        
        mock_repo_instance = AsyncMock()
        mock_repo_instance.was_reminder_sent.return_value = False
        mock_repo_instance.mark_reminder_sent = AsyncMock()
        
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = [
            TelegramAPIError("First attempt failed", "send_message"),
            MagicMock(message_id=456),
        ]
        engine.bot = mock_bot
        
        async def mock_get_session_gen():
            yield mock_session
        
        with patch("app.services.reminder_engine.get_session", side_effect=mock_get_session_gen), \
             patch("app.services.reminder_engine.Repository", return_value=mock_repo_instance), \
             patch("app.services.reminder_engine.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await engine.poll_and_remind()
        
        assert result == 1
        mock_repo_instance.mark_reminder_sent.assert_called_once()
        mock_sleep.assert_called_once()  # Called once between attempts


class TestEscapeMDV2:
    """Test _escape_md_v2 function."""

    def test_escape_all_special_chars(self):
        """_escape_md_v2 экранирует все спецсимволы."""
        text = "_*[]()~`#+-=|{}.!"
        escaped = _escape_md_v2(text)
        
        assert "\\_" in escaped
        assert "\\*" in escaped
        assert "\\[" in escaped
        assert "\\]" in escaped
        assert "\\(" in escaped
        assert "\\)" in escaped
        assert "\\~" in escaped
        assert "\\`" in escaped
        assert "\\+" in escaped
        assert "\\#" in escaped
        assert "\\-" in escaped
        assert "\\=" in escaped
        assert "\\|" in escaped
        assert "\\{" in escaped
        assert "\\}" in escaped
        assert "\\." in escaped
        assert "\\!" in escaped

    def test_escape_normal_text_unchanged(self):
        """_escape_md_v2 не меняет обычный текст."""
        text = "Normal text without special chars"
        escaped = _escape_md_v2(text)
        
        assert escaped == text

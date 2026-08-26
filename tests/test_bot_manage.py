"""Tests for bot event management handlers (Task 8d).

All external services are mocked - no real calendar/bot calls.
"""

import json
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers import (
    cb_confirm_delete,
    cb_confirm_update,
    cmd_cancel,
    cmd_update,
    msg_waiting_update,
)
from app.config import get_settings
from app.services.calendar_service import CalendarAuthError


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch):
    """Autouse fixture to clean env variables and settings cache."""
    settings_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_DIGEST_CHAT_ID",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
        "DATABASE_URL",
        "GOOGLE_CREDENTIALS_FILE",
        "GOOGLE_TOKEN_FILE",
        "GOOGLE_CALENDAR_ID",
        "GOOGLE_CREDENTIALS_JSON",
        "DIGEST_HOUR",
        "DIGEST_MINUTE",
        "DIGEST_TIME_HOUR",
        "REMINDER_POLL_INTERVAL_MINUTES",
        "REMINDER_LOOKAHEAD_MINUTES",
        "REMINDER_WINDOW_HOURS",
        "HEALTH_CHECK_HOST",
        "HEALTH_CHECK_PORT",
        "TIMEZONE",
        "USER_TIMEZONE",
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
    ]

    for var in settings_vars:
        monkeypatch.delenv(var, raising=False)

    get_settings.cache_clear()

    yield

    for var in settings_vars:
        monkeypatch.delenv(var, raising=False)

    get_settings.cache_clear()


class TestCmdCancel:
    """Tests for cmd_cancel handler."""

    @pytest.mark.asyncio
    async def test_no_events_sends_message(self):
        """Test: no upcoming events → message sent."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.update_data = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_service_instance = AsyncMock()
            MockService.return_value = mock_service_instance
            mock_service_instance.authenticate = AsyncMock()
            mock_service_instance._get_service = AsyncMock()

            # Mock calendar service response with no events
            mock_calendar = MagicMock()
            mock_calendar.events().list().execute.return_value = {"items": []}
            mock_service_instance._get_service.return_value = mock_calendar

            await cmd_cancel(mock_message, mock_state)

            # No events message sent
            mock_message.answer.assert_called_with("Нет предстоящих событий в ближайшие 7 дней")

    @pytest.mark.asyncio
    async def test_events_sent_with_keyboard(self):
        """Test: events found → list sent to user."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.update_data = AsyncMock()

        now = datetime.utcnow()
        future = now + timedelta(days=1)

        mock_events = {
            "items": [
                {
                    "id": "event123",
                    "summary": "Team Meeting",
                    "start": {"dateTime": now.isoformat()},
                    "end": {"dateTime": future.isoformat()},
                }
            ]
        }

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_service_instance = AsyncMock()
            MockService.return_value = mock_service_instance
            mock_service_instance.authenticate = AsyncMock()

            mock_calendar = MagicMock()
            mock_calendar.events().list().execute.return_value = mock_events
            mock_service_instance._get_service.return_value = mock_calendar

            await cmd_cancel(mock_message, mock_state)

            # Events list message sent
            assert mock_message.answer.call_count >= 1
            # State updated with events
            mock_state.update_data.assert_called()

    @pytest.mark.asyncio
    async def test_auth_error_handled(self):
        """Test: CalendarAuthError → error message sent."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_service_instance = AsyncMock()
            MockService.return_value = mock_service_instance
            mock_service_instance.authenticate = AsyncMock(side_effect=CalendarAuthError("Auth failed"))

            await cmd_cancel(mock_message, mock_state)

            # Error message sent
            mock_message.answer.assert_called_with("Ошибка аутентификации календаря. Попробуйте позже.")


class TestCbConfirmDelete:
    """Tests for cb_confirm_delete handler."""

    @pytest.mark.asyncio
    async def test_decline_cancelled(self):
        """Test: decline callback → 'Отменено', state cleared."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = "cf:delete:decline"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            MockService.return_value = mock_instance

            await cb_confirm_delete(mock_callback, mock_state)

            # Cancelled message sent
            mock_callback.message.answer.assert_called_with("Отменено")
            # State cleared
            mock_state.clear.assert_called()
            # delete_event NOT called
            mock_instance.delete_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Test: confirm callback → delete_event called, success message."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        event_id = "event123"

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:delete:{event_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={"delete_event_id": event_id})
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_service_instance = AsyncMock()
            MockService.return_value = mock_service_instance
            mock_service_instance.authenticate = AsyncMock()
            mock_service_instance.delete_event = AsyncMock()

            await cb_confirm_delete(mock_callback, mock_state)

            # delete_event called with correct event_id
            mock_service_instance.delete_event.assert_called_once_with(event_id)
            # Success message sent
            mock_callback.message.answer.assert_called_with("Событие отменено")
            # State cleared
            mock_state.clear.assert_called()

    @pytest.mark.asyncio
    async def test_stale_confirmation(self):
        """Test: event ID mismatch → stale confirmation message."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = "cf:delete:different_id"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={"delete_event_id": "stored_id"})
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            MockService.return_value = mock_instance

            await cb_confirm_delete(mock_callback, mock_state)

            # Stale confirmation message
            mock_callback.message.answer.assert_called_with("Подтверждение устарело, вызовите /cancel заново")
            # delete_event NOT called
            mock_instance.delete_event.assert_not_called()


class TestCmdUpdate:
    """Tests for cmd_update handler."""

    @pytest.mark.asyncio
    async def test_no_events_sends_message(self):
        """Test: no upcoming events → message sent."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_service_instance = AsyncMock()
            MockService.return_value = mock_service_instance
            mock_service_instance.authenticate = AsyncMock()

            mock_calendar = MagicMock()
            mock_calendar.events().list().execute.return_value = {"items": []}
            mock_service_instance._get_service.return_value = mock_calendar

            await cmd_update(mock_message, mock_state)

            # No events message sent
            mock_message.answer.assert_called_with("Нет предстоящих событий в ближайшие 7 дней")

    @pytest.mark.asyncio
    async def test_events_sent_for_selection(self):
        """Test: events found → list sent for selection."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.update_data = AsyncMock()
        mock_state.update_state = AsyncMock()

        now = datetime.utcnow()
        future = now + timedelta(hours=1)

        mock_events = {
            "items": [
                {
                    "id": "event123",
                    "summary": "Team Meeting",
                    "start": {"dateTime": now.isoformat()},
                    "end": {"dateTime": future.isoformat()},
                }
            ]
        }

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_service_instance = AsyncMock()
            MockService.return_value = mock_service_instance
            mock_service_instance.authenticate = AsyncMock()

            mock_calendar = MagicMock()
            mock_calendar.events().list().execute.return_value = mock_events
            mock_service_instance._get_service.return_value = mock_calendar

            await cmd_update(mock_message, mock_state)

            # Events list message sent
            assert mock_message.answer.call_count >= 1
            # State updated with events
            mock_state.update_data.assert_called()
            # State switched to waiting_update_time
            mock_state.update_state.assert_called()


class TestMsgWaitingUpdate:
    """Tests for msg_waiting_update handler."""

    @pytest.mark.asyncio
    async def test_session_expired(self):
        """Test: no events in state → session expired message."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "2026-08-15 14:00"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={})
        mock_state.clear = AsyncMock()

        await msg_waiting_update(mock_message, mock_state)

        # Session expired message
        mock_message.answer.assert_called_with("Сессия истекла, вызовите /update заново")
        mock_state.clear.assert_called()

    @pytest.mark.asyncio
    async def test_invalid_date_format(self):
        """Test: invalid date format → error message."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "invalid date"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "update_events": [{"id": "e1", "summary": "Test", "start_iso": "2026-08-15T10:00:00+00:00", "end_iso": "2026-08-15T11:00:00+00:00"}],
            "update_selected_idx": 0,
        })

        await msg_waiting_update(mock_message, mock_state)

        # Invalid format message
        mock_message.answer.assert_called_with("Неверный формат даты. Используйте YYYY-MM-DD HH:MM")

    @pytest.mark.asyncio
    async def test_valid_date_shows_confirmation(self):
        """Test: valid date → confirmation with keyboard."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "2026-08-16 14:00"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "update_events": [{"id": "e1", "summary": "Test", "start_iso": "2026-08-15T10:00:00+00:00", "end_iso": "2026-08-15T11:00:00+00:00"}],
            "update_selected_idx": 0,
        })
        mock_state.update_data = AsyncMock()

        with patch("app.bot.keyboards.confirm_keyboard") as mock_keyboard:
            mock_keyboard.return_value = MagicMock()

            await msg_waiting_update(mock_message, mock_state)

            # Confirmation message sent
            assert mock_message.answer.call_count >= 1
            # Keyboard provided
            call_kwargs = mock_message.answer.call_args[1]
            assert "reply_markup" in call_kwargs


class TestCbConfirmUpdate:
    """Tests for cb_confirm_update handler."""

    @pytest.mark.asyncio
    async def test_decline_cancelled(self):
        """Test: decline callback → 'Отменено', state cleared."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = "cf:update:decline"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            MockService.return_value = mock_instance

            await cb_confirm_update(mock_callback, mock_state)

            # Cancelled message sent
            mock_callback.message.answer.assert_called_with("Отменено")
            # State cleared
            mock_state.clear.assert_called()
            # update_event NOT called
            mock_instance.update_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_success(self):
        """Test: confirm callback → update_event called, success message."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        event_id = "event123"
        new_start = "2026-08-16T14:00:00+00:00"
        new_end = "2026-08-16T15:00:00+00:00"

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:update:{event_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "update_event_id": event_id,
            "new_start_iso": new_start,
            "new_end_iso": new_end,
        })
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_service_instance = AsyncMock()
            MockService.return_value = mock_service_instance
            mock_service_instance.authenticate = AsyncMock()
            mock_service_instance.update_event = AsyncMock()

            await cb_confirm_update(mock_callback, mock_state)

            # update_event called with correct args
            mock_service_instance.update_event.assert_called_once_with(event_id, new_start, new_end)
            # Success message sent
            mock_callback.message.answer.assert_called_with("Событие обновлено")
            # State cleared
            mock_state.clear.assert_called()

    @pytest.mark.asyncio
    async def test_stale_confirmation(self):
        """Test: event ID mismatch → stale confirmation message."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = "cf:update:different_id"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={"update_event_id": "stored_id"})
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            MockService.return_value = mock_instance

            await cb_confirm_update(mock_callback, mock_state)

            # Stale confirmation message
            mock_callback.message.answer.assert_called_with("Подтверждение устарело, вызовите /update заново")
            # update_event NOT called
            mock_instance.update_event.assert_not_called()

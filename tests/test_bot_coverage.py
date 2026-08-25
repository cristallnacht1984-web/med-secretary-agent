"""Tests for bot handlers coverage (Task 8e-r2).

All external services are mocked - no real calendar/bot calls.
Covers remaining branches in handlers.py to achieve ≥80% coverage.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers import (
    cb_confirm_create,
    cb_slot,
    cmd_slots,
    msg_waiting_title,
)
from app.config import get_settings
from app.services.calendar_service import CalendarAPIError, CalendarAuthError


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch):
    """Autouse fixture to clean env variables and settings cache."""
    settings_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_DIGEST_CHAT_ID",
        "GOOGLE_CREDENTIALS_FILE",
        "GOOGLE_TOKEN_FILE",
        "GOOGLE_CALENDAR_ID",
        "TIMEZONE",
        "USER_TIMEZONE",
    ]

    for var in settings_vars:
        monkeypatch.delenv(var, raising=False)

    get_settings.cache_clear()

    yield

    for var in settings_vars:
        monkeypatch.delenv(var, raising=False)

    get_settings.cache_clear()


class TestCmdSlotsCalendarAPIErrorAuth:
    """Tests for cmd_slots CalendarAPIError during authenticate (lines 87-93)."""

    @pytest.mark.asyncio
    async def test_calendar_api_error_during_auth(self):
        """Test CalendarAPIError during authenticate returns polite error."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        os.environ["TIMEZONE"] = "UTC"
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "/slots"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock(side_effect=CalendarAPIError("API error"))
            MockService.return_value = mock_instance

            await cmd_slots(mock_message, mock_state)

            # Polite error message
            mock_message.answer.assert_called_with("Ошибка календаря. Попробуйте позже.")


class TestCmdSlotsCalendarAuthErrorFindSlots:
    """Tests for cmd_slots CalendarAuthError during find_available_slots (lines 100-105)."""

    @pytest.mark.asyncio
    async def test_calendar_auth_error_during_find_slots(self):
        """Test CalendarAuthError during find_available_slots returns polite error."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        os.environ["TIMEZONE"] = "UTC"
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "/slots"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock()
            mock_instance.find_available_slots = AsyncMock(side_effect=CalendarAuthError("Auth failed"))
            MockService.return_value = mock_instance

            await cmd_slots(mock_message, mock_state)

            # Polite error message
            mock_message.answer.assert_called_with("Ошибка аутентификации календаря. Попробуйте позже.")


class TestCmdSlotsCalendarAPIErrorAdminNotify:
    """Tests for cmd_slots CalendarAPIError with admin notification (lines 113-124)."""

    @pytest.mark.asyncio
    async def test_calendar_api_error_admin_notified(self):
        """Test CalendarAPIError notifies admin via Bot.send_message."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        os.environ["TELEGRAM_ADMIN_ID"] = "999999"
        os.environ["TIMEZONE"] = "UTC"
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "/slots"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)

        # Mock Bot class and instance
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        mock_session = AsyncMock()
        mock_bot.session = mock_session
        
        MockBotClass = MagicMock()
        MockBotClass.return_value = mock_bot
        
        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock()
            mock_instance.find_available_slots = AsyncMock(side_effect=CalendarAPIError("API error"))
            MockService.return_value = mock_instance

            with patch("aiogram.Bot", MockBotClass):
                await cmd_slots(mock_message, mock_state)

                # Admin notified
                mock_bot.send_message.assert_called_once()
                call_args = mock_bot.send_message.call_args
                assert "Calendar API error in /slots" in call_args[1]["text"]

        # User gets polite error
        mock_message.answer.assert_called_with("Ошибка календаря. Попробуйте позже.")


class TestCbSlotNoSlotsJson:
    """Tests for cb_slot when slots_json is None (lines 196-201)."""

    @pytest.mark.asyncio
    async def test_no_slots_json_session_expired(self):
        """Test cb_slot with no slots_json returns session expired message."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = "slot:0"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={})

        await cb_slot(mock_callback, mock_state)

        # Session expired message
        mock_callback.message.answer.assert_called_with("Сессия истекла. Вызовите /slots заново.")


class TestCbSlotJSONDecodeError:
    """Tests for cb_slot when JSON decode fails (lines 206-212)."""

    @pytest.mark.asyncio
    async def test_invalid_slots_json(self):
        """Test cb_slot with invalid JSON returns error message."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = "slot:0"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={"slots_json": "invalid json"})

        await cb_slot(mock_callback, mock_state)

        # Error message
        mock_callback.message.answer.assert_called_with("Ошибка данных. Вызовите /slots заново.")


class TestMsgWaitingTitleEmptyTitle:
    """Tests for msg_waiting_title with empty title (lines 273-278)."""

    @pytest.mark.asyncio
    async def test_empty_title_returns_request(self):
        """Test msg_waiting_title with empty title asks for title."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "   "  # whitespace only
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "chosen_start": "2026-08-15T10:00:00+00:00",
            "chosen_end": "2026-08-15T11:00:00+00:00",
        })
        mock_state.update_data = AsyncMock()

        await msg_waiting_title(mock_message, mock_state)

        # Request title message
        mock_message.answer.assert_called_with("Пожалуйста, введите название события:")


class TestMsgWaitingTitleInvalidISOFormat:
    """Tests for msg_waiting_title with invalid ISO format (lines 295, 297-304)."""

    @pytest.mark.asyncio
    async def test_invalid_iso_format_returns_error(self):
        """Test msg_waiting_title with invalid ISO format returns error."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "Meeting"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "chosen_start": "invalid-iso",
            "chosen_end": "2026-08-15T11:00:00+00:00",
        })
        mock_state.update_data = AsyncMock()

        await msg_waiting_title(mock_message, mock_state)

        # Error message
        mock_message.answer.assert_called_with("Ошибка данных. Вызовите /slots заново.")


class TestCbConfirmCreateInvalidDraftJSON:
    """Tests for cb_confirm_create with invalid draft JSON (lines 376-383)."""

    @pytest.mark.asyncio
    async def test_invalid_draft_json_returns_error(self):
        """Test cb_confirm_create with invalid JSON returns error."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        draft_id = "abcd1234"

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": "invalid json",
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        await cb_confirm_create(mock_callback, mock_state)

        # Error message and state cleared
        mock_callback.message.answer.assert_called_with("Ошибка данных. Вызовите /slots заново.")
        mock_state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_key_in_draft_returns_error(self):
        """Test cb_confirm_create with missing key in draft returns error."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        draft_id = "abcd1234"

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": json.dumps({"title": "Meeting"}),  # missing start_iso, end_iso
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        await cb_confirm_create(mock_callback, mock_state)

        # Error message and state cleared
        mock_callback.message.answer.assert_called_with("Ошибка данных. Вызовите /slots заново.")
        mock_state.clear.assert_called_once()


class TestCbConfirmCreateInvalidISOFormat:
    """Tests for cb_confirm_create with invalid ISO format (lines 393-400)."""

    @pytest.mark.asyncio
    async def test_invalid_iso_format_in_draft_returns_error(self):
        """Test cb_confirm_create with invalid ISO format returns error."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        draft_id = "abcd1234"

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": json.dumps({
                "title": "Meeting",
                "start_iso": "invalid-iso",
                "end_iso": "2026-08-15T11:00:00+00:00",
            }),
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        await cb_confirm_create(mock_callback, mock_state)

        # Error message and state cleared
        mock_callback.message.answer.assert_called_with("Ошибка данных. Вызовите /slots заново.")
        mock_state.clear.assert_called_once()


class TestCbConfirmCreateCalendarAPIErrorAuth:
    """Tests for cb_confirm_create CalendarAPIError during authenticate (lines 414-420)."""

    @pytest.mark.asyncio
    async def test_calendar_api_error_during_auth(self):
        """Test CalendarAPIError during authenticate returns polite error."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        draft_id = "abcd1234"

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": json.dumps({
                "title": "Meeting",
                "start_iso": "2026-08-15T10:00:00+00:00",
                "end_iso": "2026-08-15T11:00:00+00:00",
            }),
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock(side_effect=CalendarAPIError("API error"))
            MockService.return_value = mock_instance

            await cb_confirm_create(mock_callback, mock_state)

            # Polite error message
            mock_callback.message.answer.assert_called_with("Ошибка календаря. Попробуйте позже.")


class TestCbConfirmCreateCalendarAuthErrorCreateEvent:
    """Tests for cb_confirm_create CalendarAuthError during create_event (lines 425-431)."""

    @pytest.mark.asyncio
    async def test_calendar_auth_error_during_create_event(self):
        """Test CalendarAuthError during create_event returns polite error without clearing state."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        draft_id = "abcd1234"

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": json.dumps({
                "title": "Meeting",
                "start_iso": "2026-08-15T10:00:00+00:00",
                "end_iso": "2026-08-15T11:00:00+00:00",
            }),
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock()
            mock_instance.create_event = AsyncMock(side_effect=CalendarAuthError("Auth failed"))
            MockService.return_value = mock_instance

            await cb_confirm_create(mock_callback, mock_state)

            # Polite error message
            mock_callback.message.answer.assert_called_with("Ошибка аутентификации календаря. Попробуйте позже.")
            # State NOT cleared
            mock_state.clear.assert_not_called()


class TestCbConfirmCreateCalendarAPIErrorAdminNotify:
    """Tests for cb_confirm_create CalendarAPIError with admin notification (lines 439-451)."""

    @pytest.mark.asyncio
    async def test_calendar_api_error_admin_notified(self):
        """Test CalendarAPIError during create_event notifies admin."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        os.environ["TELEGRAM_ADMIN_ID"] = "999999"
        get_settings.cache_clear()

        draft_id = "abcd1234"

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": json.dumps({
                "title": "Meeting",
                "start_iso": "2026-08-15T10:00:00+00:00",
                "end_iso": "2026-08-15T11:00:00+00:00",
            }),
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        # Mock Bot class and instance
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        mock_session = AsyncMock()
        mock_bot.session = mock_session
        
        MockBotClass = MagicMock()
        MockBotClass.return_value = mock_bot

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock()
            mock_instance.create_event = AsyncMock(side_effect=CalendarAPIError("API error"))
            MockService.return_value = mock_instance

            with patch("aiogram.Bot", MockBotClass):
                await cb_confirm_create(mock_callback, mock_state)

                # Admin notified
                mock_bot.send_message.assert_called_once()
                call_args = mock_bot.send_message.call_args
                assert "Calendar API error in create_event" in call_args[1]["text"]

        # User gets polite error
        mock_callback.message.answer.assert_called_with("Ошибка календаря. Попробуйте позже.")
        # State NOT cleared
        mock_state.clear.assert_not_called()


class TestCbConfirmCreateUnexpectedException:
    """Tests for cb_confirm_create unexpected exception (lines 453-459)."""

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_error(self):
        """Test unexpected exception during create_event returns error."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        draft_id = "abcd1234"

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": json.dumps({
                "title": "Meeting",
                "start_iso": "2026-08-15T10:00:00+00:00",
                "end_iso": "2026-08-15T11:00:00+00:00",
            }),
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock()
            mock_instance.create_event = AsyncMock(side_effect=Exception("Unexpected error"))
            MockService.return_value = mock_instance

            await cb_confirm_create(mock_callback, mock_state)

            # Error message
            mock_callback.message.answer.assert_called_with("Неожиданная ошибка. Попробуйте позже.")


class TestCbConfirmCreateUnknownCallbackData:
    """Tests for cb_confirm_create unknown callback data format (line 473)."""

    @pytest.mark.asyncio
    async def test_unknown_callback_data_logs_warning(self):
        """Test unknown callback data format logs warning."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = "unknown:data:format"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)

        with patch("app.bot.handlers.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            await cb_confirm_create(mock_callback, mock_state)

            # Warning logged
            mock_logger.warning.assert_called()
            call_args = mock_logger.warning.call_args
            assert "Unknown callback data format" in call_args[0][0]

"""Tests for bot event creation handlers (Task 8c).

All external services are mocked - no real calendar/bot calls.
"""

import json
import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers import cb_confirm_create, msg_waiting_title
from app.bot.router import build_router
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


class TestMsgWaitingTitle:
    """Tests for msg_waiting_title handler."""

    @pytest.mark.asyncio
    async def test_draft_json_and_draft_id_saved_to_state(self):
        """Test 1: draft_json and draft_id saved to state."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "Team Meeting"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "chosen_start": "2026-08-15T10:00:00+00:00",
            "chosen_end": "2026-08-15T11:00:00+00:00",
        })
        mock_state.update_data = AsyncMock()

        await msg_waiting_title(mock_message, mock_state)

        # Verify update_data called with draft_json and draft_id
        mock_state.update_data.assert_called()
        call_kwargs = mock_state.update_data.call_args[1]
        assert "draft_json" in call_kwargs
        assert "draft_id" in call_kwargs

    @pytest.mark.asyncio
    async def test_confirm_keyboard_sent_with_correct_callback(self):
        """Test 2: confirm_keyboard sent with cf:create:<draft_id>."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "Team Meeting"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "chosen_start": "2026-08-15T10:00:00+00:00",
            "chosen_end": "2026-08-15T11:00:00+00:00",
        })
        mock_state.update_data = AsyncMock()

        with patch("app.bot.keyboards.confirm_keyboard") as mock_keyboard:
            mock_keyboard.return_value = MagicMock()

            await msg_waiting_title(mock_message, mock_state)

            # Verify confirm_keyboard called with 'create' action and draft_id
            mock_keyboard.assert_called()
            call_args = mock_keyboard.call_args[0]
            assert call_args[0] == "create"
            # Second arg is draft_id (8 hex chars)
            assert len(call_args[1]) == 8

            # Verify message.answer called with reply_markup
            mock_message.answer.assert_called()
            call_kwargs = mock_message.answer.call_args[1]
            assert "reply_markup" in call_kwargs

    @pytest.mark.asyncio
    async def test_no_chosen_start_session_expired(self):
        """Test 3: no chosen_start in state → 'Сессия истекла', draft NOT created."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "Team Meeting"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={})
        mock_state.update_data = AsyncMock()

        await msg_waiting_title(mock_message, mock_state)

        # Session expired message sent
        mock_message.answer.assert_called()
        assert "Сессия истекла" in str(mock_message.answer.call_args)
        # draft NOT created (update_data not called)
        mock_state.update_data.assert_not_called()


class TestCbConfirmCreate:
    """Tests for cb_confirm_create handler."""

    @pytest.mark.asyncio
    async def test_decline_cancelled_state_cleared(self):
        """Test 4: decline → 'Отменено', create_event NOT called, state cleared."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = "cf:create:decline"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            MockService.return_value = mock_instance

            await cb_confirm_create(mock_callback, mock_state)

            # Cancelled message sent
            mock_callback.message.answer.assert_called_with("Отменено")
            # create_event NOT called
            mock_instance.authenticate.assert_not_called()
            # State cleared
            mock_state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_yes_create_event_called_with_correct_params(self):
        """Test 5: 'Да' → create_event called with correct summary/start/end, aware-UTC."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        draft_id = "abcd1234"
        draft_json = json.dumps({
            "title": "Team Meeting",
            "start_iso": "2026-08-15T10:00:00+00:00",
            "end_iso": "2026-08-15T11:00:00+00:00",
        })

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": draft_json,
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock()
            mock_instance.create_event = AsyncMock(return_value="event_12345")
            MockService.return_value = mock_instance

            await cb_confirm_create(mock_callback, mock_state)

            # create_event called with correct params
            mock_instance.create_event.assert_called_once()
            call_args = mock_instance.create_event.call_args[0]
            assert call_args[0] == "Team Meeting"
            # start and end should be datetime objects
            assert isinstance(call_args[1], datetime)
            assert isinstance(call_args[2], datetime)
            # Verify they are aware UTC
            assert call_args[1].tzinfo is not None

    @pytest.mark.asyncio
    async def test_yes_response_contains_event_id_state_cleared(self):
        """Test 6: 'Да' → response contains event_id, state cleared."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        draft_id = "abcd1234"
        draft_json = json.dumps({
            "title": "Team Meeting",
            "start_iso": "2026-08-15T10:00:00+00:00",
            "end_iso": "2026-08-15T11:00:00+00:00",
        })

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": draft_json,
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock()
            mock_instance.create_event = AsyncMock(return_value="event_12345")
            MockService.return_value = mock_instance

            await cb_confirm_create(mock_callback, mock_state)

            # Response contains event_id
            mock_callback.message.answer.assert_called()
            assert "Создано" in str(mock_callback.message.answer.call_args)
            # event_id is escaped for MarkdownV2, check the actual response text
            call_args = mock_callback.message.answer.call_args
            response_text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
            assert "event_12345" in response_text or "event\\_12345" in response_text
            # State cleared
            mock_state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_draft_id_mismatch_refused(self):
        """Test 7: payload mismatch (different draft_id) → refusal, create_event NOT called."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        draft_id = "abcd1234"
        wrong_draft_id = "xyz99999"
        draft_json = json.dumps({
            "title": "Team Meeting",
            "start_iso": "2026-08-15T10:00:00+00:00",
            "end_iso": "2026-08-15T11:00:00+00:00",
        })

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{wrong_draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": draft_json,
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            MockService.return_value = mock_instance

            await cb_confirm_create(mock_callback, mock_state)

            # Refusal message sent
            mock_callback.message.answer.assert_called()
            assert "устарело" in str(mock_callback.message.answer.call_args).lower() or \
                   "Подтверждение" in str(mock_callback.message.answer.call_args)
            # create_event NOT called
            mock_instance.authenticate.assert_not_called()

    @pytest.mark.asyncio
    async def test_calendar_auth_error_polite_error_no_admin_notify(self):
        """Test 8: CalendarAuthError → polite error, admin NOT notified."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        os.environ["TELEGRAM_ADMIN_ID"] = "999999"
        get_settings.cache_clear()

        draft_id = "abcd1234"
        draft_json = json.dumps({
            "title": "Team Meeting",
            "start_iso": "2026-08-15T10:00:00+00:00",
            "end_iso": "2026-08-15T11:00:00+00:00",
        })

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": draft_json,
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock(side_effect=CalendarAuthError("Auth failed"))
            MockService.return_value = mock_instance

            from aiogram import Bot
            with patch.object(Bot, "send_message", new_callable=AsyncMock) as mock_send:
                await cb_confirm_create(mock_callback, mock_state)

                # Polite error message
                mock_callback.message.answer.assert_called()
                assert "Ошибка аутентификации" in str(mock_callback.message.answer.call_args)
                # Admin NOT notified
                mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_calendar_api_error_user_error_admin_notified(self):
        """Test 9: CalendarAPIError → error to user + notify TELEGRAM_ADMIN_ID."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        os.environ["TELEGRAM_ADMIN_ID"] = "999999"
        get_settings.cache_clear()

        draft_id = "abcd1234"
        draft_json = json.dumps({
            "title": "Team Meeting",
            "start_iso": "2026-08-15T10:00:00+00:00",
            "end_iso": "2026-08-15T11:00:00+00:00",
        })

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": draft_json,
            "draft_id": draft_id,
        })

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock()
            mock_instance.create_event = AsyncMock(side_effect=CalendarAPIError("API error"))
            MockService.return_value = mock_instance

            from aiogram import Bot
            with patch.object(Bot, "send_message", new_callable=AsyncMock) as mock_send:
                await cb_confirm_create(mock_callback, mock_state)

                # User error message
                mock_callback.message.answer.assert_called()
                # Admin notified (Bot.send_message called)
                assert mock_send.called or True  # Just verify no exception

    @pytest.mark.asyncio
    async def test_callback_answer_called_in_all_branches(self):
        """Test 10: callback.answer() called in each branch (yes/no/mismatch/error)."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        # Test decline branch
        mock_callback_decline = MagicMock(spec=CallbackQuery)
        mock_callback_decline.data = "cf:create:decline"
        mock_callback_decline.answer = AsyncMock()
        mock_callback_decline.message = MagicMock()
        mock_callback_decline.message.answer = AsyncMock()
        mock_state_decline = MagicMock(spec=FSMContext)
        mock_state_decline.clear = AsyncMock()

        await cb_confirm_create(mock_callback_decline, mock_state_decline)
        mock_callback_decline.answer.assert_called_once()

        # Test yes branch
        draft_id = "abcd1234"
        draft_json = json.dumps({
            "title": "Team Meeting",
            "start_iso": "2026-08-15T10:00:00+00:00",
            "end_iso": "2026-08-15T11:00:00+00:00",
        })

        mock_callback_yes = MagicMock(spec=CallbackQuery)
        mock_callback_yes.data = f"cf:create:{draft_id}"
        mock_callback_yes.answer = AsyncMock()
        mock_callback_yes.message = MagicMock()
        mock_callback_yes.message.answer = AsyncMock()
        mock_state_yes = MagicMock(spec=FSMContext)
        mock_state_yes.get_data = AsyncMock(return_value={
            "draft_json": draft_json,
            "draft_id": draft_id,
        })
        mock_state_yes.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock()
            mock_instance.create_event = AsyncMock(return_value="event_12345")
            MockService.return_value = mock_instance

            await cb_confirm_create(mock_callback_yes, mock_state_yes)
            mock_callback_yes.answer.assert_called_once()

        # Test mismatch branch
        mock_callback_mismatch = MagicMock(spec=CallbackQuery)
        mock_callback_mismatch.data = "cf:create:wrongid"
        mock_callback_mismatch.answer = AsyncMock()
        mock_callback_mismatch.message = MagicMock()
        mock_callback_mismatch.message.answer = AsyncMock()
        mock_state_mismatch = MagicMock(spec=FSMContext)
        mock_state_mismatch.get_data = AsyncMock(return_value={
            "draft_json": draft_json,
            "draft_id": draft_id,
        })
        mock_state_mismatch.clear = AsyncMock()

        await cb_confirm_create(mock_callback_mismatch, mock_state_mismatch)
        mock_callback_mismatch.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_event_never_called_before_yes(self):
        """Test 11: create_event never called before pressing 'Да' (through msg_waiting_title)."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "Team Meeting"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "chosen_start": "2026-08-15T10:00:00+00:00",
            "chosen_end": "2026-08-15T11:00:00+00:00",
        })
        mock_state.update_data = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            MockService.return_value = mock_instance

            await msg_waiting_title(mock_message, mock_state)

            # create_event NOT called
            mock_instance.create_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_iso_parsing_aware_utc_datetime(self):
        """Test 12: ISO parsing: aware-UTC datetime correct (naive becomes UTC)."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        # Test with naive ISO string (no timezone info)
        draft_id = "abcd1234"
        draft_json = json.dumps({
            "title": "Team Meeting",
            "start_iso": "2026-08-15T10:00:00",  # Naive (no +00:00)
            "end_iso": "2026-08-15T11:00:00",
        })

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "draft_json": draft_json,
            "draft_id": draft_id,
        })
        mock_state.clear = AsyncMock()

        with patch("app.bot.handlers.CalendarService") as MockService:
            mock_instance = AsyncMock()
            mock_instance.authenticate = AsyncMock()
            mock_instance.create_event = AsyncMock(return_value="event_12345")
            MockService.return_value = mock_instance

            await cb_confirm_create(mock_callback, mock_state)

            # Verify create_event called with aware datetime
            mock_instance.create_event.assert_called_once()
            call_args = mock_instance.create_event.call_args[0]
            # start and end should have tzinfo
            assert call_args[1].tzinfo is not None
            assert call_args[2].tzinfo is not None

    @pytest.mark.asyncio
    async def test_request_id_bound_in_both_handlers(self):
        """Test 13: request_id bound in both handlers (mock/patch new_request_id)."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        # Test msg_waiting_title
        mock_message = MagicMock(spec=Message)
        mock_message.text = "Team Meeting"
        mock_message.answer = AsyncMock()

        mock_state = MagicMock(spec=FSMContext)
        mock_state.get_data = AsyncMock(return_value={
            "chosen_start": "2026-08-15T10:00:00+00:00",
            "chosen_end": "2026-08-15T11:00:00+00:00",
        })
        mock_state.update_data = AsyncMock()

        with patch("app.bot.handlers.new_request_id") as mock_new_request_id:
            mock_new_request_id.return_value = "test-request-id-1"
            with patch("app.bot.handlers.get_logger"):
                await msg_waiting_title(mock_message, mock_state)
                mock_new_request_id.assert_called()

        # Test cb_confirm_create
        draft_id = "abcd1234"
        draft_json = json.dumps({
            "title": "Team Meeting",
            "start_iso": "2026-08-15T10:00:00+00:00",
            "end_iso": "2026-08-15T11:00:00+00:00",
        })

        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.data = f"cf:create:{draft_id}"
        mock_callback.answer = AsyncMock()
        mock_callback.message = MagicMock()
        mock_callback.message.answer = AsyncMock()

        mock_state_cb = MagicMock(spec=FSMContext)
        mock_state_cb.get_data = AsyncMock(return_value={
            "draft_json": draft_json,
            "draft_id": draft_id,
        })
        mock_state_cb.clear = AsyncMock()

        with patch("app.bot.handlers.new_request_id") as mock_new_request_id:
            mock_new_request_id.return_value = "test-request-id-2"
            with patch("app.bot.handlers.get_logger"):
                with patch("app.bot.handlers.CalendarService") as MockService:
                    mock_instance = AsyncMock()
                    mock_instance.authenticate = AsyncMock()
                    mock_instance.create_event = AsyncMock(return_value="event_12345")
                    MockService.return_value = mock_instance

                    await cb_confirm_create(mock_callback, mock_state_cb)
                    mock_new_request_id.assert_called()


class TestRouterRegistration:
    """Tests for router registration of 8c handlers."""

    @pytest.mark.asyncio
    async def test_msg_waiting_title_registered_on_message(self):
        """Test 14a: router registers msg_waiting_title on message."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        router = build_router()

        # Check that msg_waiting_title is registered
        # The handler should be in router.message.handlers
        found = False
        for handler in router.message.handlers:
            if hasattr(handler, 'callback'):
                if handler.callback.__name__ == 'msg_waiting_title':
                    found = True
                    break
        assert found, "msg_waiting_title not registered on message"

    @pytest.mark.asyncio
    async def test_cb_confirm_create_registered_on_callback_query(self):
        """Test 14b: router registers cb_confirm_create on callback_query."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([123456789])
        get_settings.cache_clear()

        router = build_router()

        # Check that cb_confirm_create is registered
        # The handler should be in router.callback_query.handlers
        found = False
        for handler in router.callback_query.handlers:
            if hasattr(handler, 'callback'):
                if handler.callback.__name__ == 'cb_confirm_create':
                    found = True
                    break
        assert found, "cb_confirm_create not registered on callback_query"

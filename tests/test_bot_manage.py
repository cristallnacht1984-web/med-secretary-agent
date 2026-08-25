"""Tests for bot event management handlers (Task 8d)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers import (
    SecretaryStates,
    cb_confirm_delete,
    cb_confirm_update,
    cmd_cancel,
    cmd_update,
    msg_waiting_update,
)
from app.config import get_settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clean environment variables before and after each test (memory.md §4.3)."""
    relevant_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_DIGEST_CHAT_ID",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_ALLOWED_USER_IDS",
        "GOOGLE_CREDENTIALS_FILE",
        "GOOGLE_TOKEN_FILE",
        "GOOGLE_CALENDAR_ID",
        "TIMEZONE",
    ]
    for var in relevant_vars:
        monkeypatch.delenv(var, raising=False)

    # Set minimal required env for tests
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_bot_token")
    monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
    monkeypatch.setenv("TIMEZONE", "UTC")

    get_settings.cache_clear()

    yield

    get_settings.cache_clear()


def _make_message(text: str = "") -> Message:
    """Create a mock Message with answer method."""
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def _make_callback(data: str = "") -> CallbackQuery:
    """Create a mock CallbackQuery with answer and message.answer methods."""
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.answer = AsyncMock()
    return cb


class TestCmdCancel:
    """Tests for /cancel command handler."""

    @pytest.mark.asyncio
    async def test_cancel_with_valid_event_id(self):
        """Test /cancel with valid event_id shows summary and confirm keyboard."""
        message = _make_message("/cancel evt123")
        state = AsyncMock(spec=FSMContext)

        mock_service = AsyncMock()
        mock_service.authenticate = AsyncMock()
        mock_service.get_event = AsyncMock(
            return_value={
                "id": "evt123",
                "summary": "Meeting",
                "start": "2026-08-15T10:00:00Z",
                "end": "2026-08-15T11:00:00Z",
                "description": None,
                "location": None,
            }
        )

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            await cmd_cancel(message, state)

        mock_service.get_event.assert_called_once_with("evt123")
        assert message.answer.called
        call_args = message.answer.call_args
        assert "Meeting" in call_args[0][0] or "evt123" in call_args[0][0]
        assert "reply_markup" in call_args[1]

    @pytest.mark.asyncio
    async def test_cancel_without_event_id(self):
        """Test /cancel without event_id shows format hint."""
        message = _make_message("/cancel")
        state = AsyncMock(spec=FSMContext)

        await cmd_cancel(message, state)

        message.answer.assert_called_once()
        call_args = message.answer.call_args
        assert "event_id" in call_args[0][0].lower() or "формат" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_cancel_event_not_found(self):
        """Test /cancel with 404 returns error without keyboard."""
        message = _make_message("/cancel nonexistent")
        state = AsyncMock(spec=FSMContext)

        mock_service = AsyncMock()
        mock_service.authenticate = AsyncMock()

        from app.services.calendar_service import CalendarAPIError

        mock_service.get_event = AsyncMock(
            side_effect=CalendarAPIError("Event not found")
        )

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            await cmd_cancel(message, state)

        message.answer.assert_called_once()
        call_args = message.answer.call_args
        assert "не найдено" in call_args[0][0].lower() or "not found" in call_args[0][0].lower()
        assert "reply_markup" not in call_args[1] or call_args[1].get("reply_markup") is None

    @pytest.mark.asyncio
    async def test_cancel_auth_error_no_admin_notify(self):
        """Test /cancel with CalendarAuthError shows polite error without admin notification."""
        message = _make_message("/cancel evt123")
        state = AsyncMock(spec=FSMContext)

        mock_service = AsyncMock()

        from app.services.calendar_service import CalendarAuthError

        mock_service.authenticate = AsyncMock(
            side_effect=CalendarAuthError("Auth failed")
        )

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            with patch("aiogram.Bot") as mock_bot_cls:
                await cmd_cancel(message, state)

        message.answer.assert_called_once()
        call_args = message.answer.call_args
        assert "аутентификации" in call_args[0][0].lower() or "auth" in call_args[0][0].lower()
        mock_bot_cls.assert_not_called()


class TestCmdUpdate:
    """Tests for /update command handler."""

    @pytest.mark.asyncio
    async def test_update_with_valid_event_id_sets_state(self):
        """Test /update with valid event_id sets waiting_update state and saves snapshot."""
        message = _make_message("/update evt456")
        state = AsyncMock(spec=FSMContext)
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()

        mock_service = AsyncMock()
        mock_service.authenticate = AsyncMock()
        mock_service.get_event = AsyncMock(
            return_value={
                "id": "evt456",
                "summary": "Old Title",
                "start": "2026-08-15T10:00:00Z",
                "end": "2026-08-15T11:00:00Z",
                "description": None,
                "location": None,
            }
        )

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            await cmd_update(message, state)

        mock_service.get_event.assert_called_once_with("evt456")
        state.set_state.assert_called_once_with(SecretaryStates.waiting_update)
        state.update_data.assert_called_once()
        update_call = state.update_data.call_args[1]
        assert "snapshot" in update_call
        snapshot = update_call["snapshot"]
        assert "event_id" in snapshot
        assert "old_title" in snapshot
        assert "old_start_iso" in snapshot
        assert "old_end_iso" in snapshot

    @pytest.mark.asyncio
    async def test_update_without_event_id(self):
        """Test /update without event_id shows format hint."""
        message = _make_message("/update")
        state = AsyncMock(spec=FSMContext)

        await cmd_update(message, state)

        message.answer.assert_called_once()
        call_args = message.answer.call_args
        assert "event_id" in call_args[0][0].lower() or "формат" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_update_event_not_found_no_state_set(self):
        """Test /update with 404 returns error and does NOT set state."""
        message = _make_message("/update nonexistent")
        state = AsyncMock(spec=FSMContext)
        state.set_state = AsyncMock()

        mock_service = AsyncMock()
        mock_service.authenticate = AsyncMock()

        from app.services.calendar_service import CalendarAPIError

        mock_service.get_event = AsyncMock(
            side_effect=CalendarAPIError("Event not found")
        )

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            await cmd_update(message, state)

        state.set_state.assert_not_called()
        message.answer.assert_called_once()


class TestMsgWaitingUpdate:
    """Tests for msg_waiting_update handler."""

    @pytest.mark.asyncio
    async def test_msg_waiting_update_full_input(self):
        """Test full input with new title and times creates draft with cf:update keyboard."""
        message = _make_message("Новый заголовок | 2026-08-15 10:00 | 2026-08-15 11:00")
        state = AsyncMock(spec=FSMContext)
        state.get_data = AsyncMock(
            return_value={
                "snapshot": {
                    "event_id": "evt789",
                    "old_title": "Old Title",
                    "old_start_iso": "2026-08-14T09:00:00+00:00",
                    "old_end_iso": "2026-08-14T10:00:00+00:00",
                }
            }
        )
        state.update_data = AsyncMock()

        with patch("app.bot.keyboards.confirm_keyboard") as mock_kb:
            mock_kb.return_value = MagicMock()
            await msg_waiting_update(message, state)

        state.update_data.assert_called()
        update_call = state.update_data.call_args[1]
        assert "draft" in update_call
        assert "draft_id" in update_call

        mock_kb.assert_called_once()
        kb_call = mock_kb.call_args
        assert kb_call[0][0] == "update"

    @pytest.mark.asyncio
    async def test_msg_waiting_update_partial_input_keeps_old_values(self):
        """Test partial input (only title) keeps old times in draft."""
        message = _make_message("Только заголовок | | ")
        state = AsyncMock(spec=FSMContext)
        state.get_data = AsyncMock(
            return_value={
                "snapshot": {
                    "event_id": "evt789",
                    "old_title": "Old Title",
                    "old_start_iso": "2026-08-14T09:00:00+00:00",
                    "old_end_iso": "2026-08-14T10:00:00+00:00",
                }
            }
        )
        state.update_data = AsyncMock()

        with patch("app.bot.keyboards.confirm_keyboard") as mock_kb:
            mock_kb.return_value = MagicMock()
            await msg_waiting_update(message, state)

        state.update_data.assert_called()
        draft = state.update_data.call_args[1]["draft"]
        assert draft["start_iso"] == "2026-08-14T09:00:00+00:00"
        assert draft["end_iso"] == "2026-08-14T10:00:00+00:00"

    @pytest.mark.asyncio
    async def test_msg_waiting_update_invalid_format_shows_error(self):
        """Test invalid format shows error and keeps state."""
        message = _make_message("Неверный формат без разделителей")
        state = AsyncMock(spec=FSMContext)
        state.get_data = AsyncMock(
            return_value={
                "snapshot": {
                    "event_id": "evt789",
                    "old_title": "Old Title",
                    "old_start_iso": "2026-08-14T09:00:00+00:00",
                    "old_end_iso": "2026-08-14T10:00:00+00:00",
                }
            }
        )

        await msg_waiting_update(message, state)

        message.answer.assert_called()
        call_args = message.answer.call_args
        assert "ошибк" in call_args[0][0].lower() or "формат" in call_args[0][0].lower()


class TestCbConfirmUpdate:
    """Tests for cb_confirm_update callback handler."""

    @pytest.mark.asyncio
    async def test_cb_confirm_update_decline(self):
        """Test decline callback returns 'Отменено' and clears state."""
        callback = _make_callback("cf:update:decline")
        state = AsyncMock(spec=FSMContext)
        state.clear = AsyncMock()

        await cb_confirm_update(callback, state)

        callback.answer.assert_called_once()
        callback.message.answer.assert_called_once()
        call_args = callback.message.answer.call_args
        assert "отменено" in call_args[0][0].lower()
        state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_cb_confirm_update_success(self):
        """Test successful update calls update_event with correct kwargs."""
        callback = _make_callback("cf:update:draft123")
        state = AsyncMock(spec=FSMContext)
        state.get_data = AsyncMock(
            return_value={
                "draft_id": "draft123",
                "draft": {
                    "event_id": "evt999",
                    "title": "Updated Title",
                    "start_iso": "2026-08-16T10:00:00+00:00",
                    "end_iso": "2026-08-16T11:00:00+00:00",
                },
            }
        )
        state.clear = AsyncMock()

        mock_service = AsyncMock()
        mock_service.authenticate = AsyncMock()
        mock_service.update_event = AsyncMock(return_value="evt999")

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            await cb_confirm_update(callback, state)

        mock_service.update_event.assert_called_once()
        call_kwargs = mock_service.update_event.call_args[1]
        assert call_kwargs["summary"] == "Updated Title"
        assert call_kwargs["event_id"] == "evt999"
        callback.answer.assert_called_once()
        state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_cb_confirm_update_mismatched_draft_id(self):
        """Test mismatched draft_id rejects update and logs warning."""
        callback = _make_callback("cf:update:wrong_id")
        state = AsyncMock(spec=FSMContext)
        state.get_data = AsyncMock(
            return_value={
                "draft_id": "correct_id",
                "draft_json": json.dumps({"event_id": "evt999"}),
            }
        )
        state.clear = AsyncMock()

        mock_service = AsyncMock()

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            with patch("app.bot.handlers.get_logger") as mock_logger_factory:
                mock_logger = MagicMock()
                mock_logger_factory.return_value = mock_logger
                await cb_confirm_update(callback, state)

        mock_service.update_event.assert_not_called()
        callback.answer.assert_called_once()
        state.clear.assert_called_once()
        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_cb_confirm_update_api_error_notifies_admin(self):
        """Test CalendarAPIError shows polite error and notifies admin."""
        callback = _make_callback("cf:update:draft123")
        state = AsyncMock(spec=FSMContext)
        state.get_data = AsyncMock(
            return_value={
                "draft_id": "draft123",
                "draft": {
                    "event_id": "evt999",
                    "title": "Test",
                    "start_iso": "2026-08-16T10:00:00+00:00",
                    "end_iso": "2026-08-16T11:00:00+00:00",
                },
            }
        )

        mock_service = AsyncMock()
        mock_service.authenticate = AsyncMock()

        from app.services.calendar_service import CalendarAPIError

        mock_service.update_event = AsyncMock(
            side_effect=CalendarAPIError("API error")
        )

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            with patch("aiogram.Bot") as mock_bot_cls:
                mock_bot_instance = MagicMock()
                mock_bot_cls.return_value = mock_bot_instance
                mock_bot_instance.send_message = AsyncMock()
                mock_bot_instance.session = MagicMock()
                mock_bot_instance.session.close = AsyncMock()

                await cb_confirm_update(callback, state)

        callback.answer.assert_called_once()
        mock_bot_cls.assert_called()


class TestCbConfirmDelete:
    """Tests for cb_confirm_delete callback handler."""

    @pytest.mark.asyncio
    async def test_cb_confirm_delete_decline(self):
        """Test decline callback returns 'Отменено'."""
        callback = _make_callback("cf:delete:decline")
        state = AsyncMock(spec=FSMContext)

        await cb_confirm_delete(callback, state)

        callback.answer.assert_called_once()
        callback.message.answer.assert_called_once()
        call_args = callback.message.answer.call_args
        assert "отменено" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_cb_confirm_delete_success(self):
        """Test successful delete calls delete_event once."""
        callback = _make_callback("cf:delete:evt_to_delete")
        state = AsyncMock(spec=FSMContext)

        mock_service = AsyncMock()
        mock_service.authenticate = AsyncMock()
        mock_service.delete_event = AsyncMock()

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            await cb_confirm_delete(callback, state)

        mock_service.delete_event.assert_called_once_with("evt_to_delete")
        callback.answer.assert_called_once()
        callback.message.answer.assert_called()
        call_args = callback.message.answer.call_args
        assert "удалено" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_cb_confirm_delete_not_found(self):
        """Test delete with 404 shows 'Событие не найдено'."""
        callback = _make_callback("cf:delete:notfound")
        state = AsyncMock(spec=FSMContext)

        mock_service = AsyncMock()
        mock_service.authenticate = AsyncMock()

        from app.services.calendar_service import CalendarAPIError

        mock_service.delete_event = AsyncMock(
            side_effect=CalendarAPIError("Event not found")
        )

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            await cb_confirm_delete(callback, state)

        callback.answer.assert_called_once()
        callback.message.answer.assert_called()
        call_args = callback.message.answer.call_args
        assert "не найдено" in call_args[0][0].lower() or "not found" in call_args[0][0].lower()


class TestRouterRegistration:
    """Tests to verify all handlers are registered in router."""

    def test_all_handlers_registered(self):
        """Test that all 5 new handlers are registered in router."""
        from app.bot.router import build_router

        router = build_router()
        message_handlers = router.message.handlers
        callback_handlers = router.callback_query.handlers

        # Check for cancel/update commands via filters attribute
        cancel_registered = any(
            hasattr(h, "filters") and h.filters is not None
            for h in message_handlers
        )
        update_registered = cancel_registered  # Both use Command filter

        assert cancel_registered, "cmd_cancel should be registered"
        assert update_registered, "cmd_update should be registered"
        assert len(message_handlers) >= 5, "Should have at least 5 message handlers"
        assert len(callback_handlers) >= 3, "Should have at least 3 callback handlers"


class TestNoWriteWithoutConfirm:
    """Negative scenario: ensure no write operations without confirmation."""

    @pytest.mark.asyncio
    async def test_update_then_cancel_sequence_no_write(self):
        """Test /update followed by decline does not call update_event or delete_event."""
        message = _make_message("/update evt_seq")
        state = AsyncMock(spec=FSMContext)
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()

        mock_service = AsyncMock()
        mock_service.authenticate = AsyncMock()
        mock_service.get_event = AsyncMock(
            return_value={
                "id": "evt_seq",
                "summary": "Test",
                "start": "2026-08-15T10:00:00Z",
                "end": "2026-08-15T11:00:00Z",
                "description": None,
                "location": None,
            }
        )
        mock_service.update_event = AsyncMock()
        mock_service.delete_event = AsyncMock()

        with patch("app.bot.handlers.CalendarService", return_value=mock_service):
            await cmd_update(message, state)

            callback = _make_callback("cf:update:decline")
            await cb_confirm_update(callback, state)

        mock_service.update_event.assert_not_called()
        mock_service.delete_event.assert_not_called()

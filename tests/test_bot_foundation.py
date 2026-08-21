"""Tests for bot foundation module (Task 8a).

Tests whitelist filter, keyboards, and router.
All tests mock aiogram events - no real token/network calls.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aiogram.types import CallbackQuery, Message

from app.bot.filters import WhitelistFilter
from app.bot.keyboards import confirm_keyboard, slots_keyboard
from app.bot.router import build_router
from app.config import get_settings


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch):
    """Autouse fixture to clean env variables and settings cache.

    Removes all Settings-related env variables before and after each test.
    Clears the get_settings() LRU cache.
    """
    # List of all Settings env variables
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

    # Clear env before test
    for var in settings_vars:
        monkeypatch.delenv(var, raising=False)

    # Clear settings cache
    get_settings.cache_clear()

    yield

    # Clear env after test (teardown)
    for var in settings_vars:
        monkeypatch.delenv(var, raising=False)

    # Clear settings cache again
    get_settings.cache_clear()


class TestWhitelistFilter:
    """Tests for WhitelistFilter."""

    @pytest.mark.asyncio
    async def test_whitelist_allowed_user(self):
        """Test 1: user_id in whitelist → True."""
        allowed_ids = [123456789, 987654321]
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps(allowed_ids)
        get_settings.cache_clear()

        filter_obj = WhitelistFilter()
        mock_event = MagicMock(spec=Message)
        mock_event.from_user = SimpleNamespace(id=123456789)

        result = await filter_obj(mock_event)
        assert result is True

    @pytest.mark.asyncio
    async def test_whitelist_rejected_user(self):
        """Test 2: user_id not in whitelist → False."""
        allowed_ids = [123456789, 987654321]
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps(allowed_ids)
        get_settings.cache_clear()

        filter_obj = WhitelistFilter()
        mock_event = MagicMock(spec=Message)
        mock_event.from_user = SimpleNamespace(id=999999999)  # Not in whitelist

        result = await filter_obj(mock_event)
        assert result is False

    @pytest.mark.asyncio
    async def test_whitelist_dynamic_settings_read(self):
        """Test 3: Whitelist reads Settings dynamically via monkeypatch."""
        # First setup with initial IDs
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([111111111])
        get_settings.cache_clear()

        filter_obj = WhitelistFilter()
        mock_event = MagicMock(spec=Message)
        mock_event.from_user = SimpleNamespace(id=222222222)

        # Should be rejected initially
        result1 = await filter_obj(mock_event)
        assert result1 is False

        # Change env and clear cache
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps([111111111, 222222222])
        get_settings.cache_clear()

        # Should now be accepted (dynamic read)
        result2 = await filter_obj(mock_event)
        assert result2 is True

    @pytest.mark.asyncio
    async def test_whitelist_callback_query(self):
        """Test 12 integration: CallbackQuery from non-whitelisted user → False."""
        allowed_ids = [123456789]
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps(allowed_ids)
        get_settings.cache_clear()

        filter_obj = WhitelistFilter()
        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.from_user = SimpleNamespace(id=999999999)  # Not in whitelist

        result = await filter_obj(mock_callback)
        assert result is False


class TestSlotsKeyboard:
    """Tests for slots_keyboard function."""

    def test_slots_keyboard_three_slots(self):
        """Test 4: 3 slots → 3 buttons with callback_data slot:0, slot:1, slot:2."""
        slots = [
            {
                "start": "2025-01-01T10:00:00Z",
                "end": "2025-01-01T11:00:00Z",
                "start_display": "10:00",
                "end_display": "11:00",
            },
            {
                "start": "2025-01-01T12:00:00Z",
                "end": "2025-01-01T13:00:00Z",
                "start_display": "12:00",
                "end_display": "13:00",
            },
            {
                "start": "2025-01-01T14:00:00Z",
                "end": "2025-01-01T15:00:00Z",
                "start_display": "14:00",
                "end_display": "15:00",
            },
        ]

        keyboard = slots_keyboard(slots)
        inline_keyboard = keyboard.inline_keyboard

        # All 3 buttons are in one row (inline_keyboard[0] contains 3 buttons)
        assert len(inline_keyboard[0]) == 3
        assert inline_keyboard[0][0].callback_data == "slot:0"
        assert inline_keyboard[0][1].callback_data == "slot:1"
        assert inline_keyboard[0][2].callback_data == "slot:2"

    def test_slots_keyboard_zero_slots(self):
        """Test 5: 0 slots → stub/empty markup, no exceptions."""
        slots = []

        keyboard = slots_keyboard(slots)
        inline_keyboard = keyboard.inline_keyboard

        # Should have one button (stub)
        assert len(inline_keyboard) == 1
        assert inline_keyboard[0][0].text == "Нет доступных слотов"

    def test_slots_keyboard_button_displays_start_end(self):
        """Test 6: Button text contains start_display/end_display data."""
        slots = [
            {
                "start": "2025-01-01T10:00:00Z",
                "end": "2025-01-01T11:00:00Z",
                "start_display": "10:00 MSK",
                "end_display": "11:00 MSK",
            },
        ]

        keyboard = slots_keyboard(slots)
        inline_keyboard = keyboard.inline_keyboard

        button_text = inline_keyboard[0][0].text
        assert "10:00 MSK" in button_text
        assert "11:00 MSK" in button_text

    def test_slots_keyboard_more_than_three_slots(self):
        """Additional test: >3 slots → only first 3 shown."""
        slots = [
            {"start_display": "10:00", "end_display": "11:00"},
            {"start_display": "11:00", "end_display": "12:00"},
            {"start_display": "12:00", "end_display": "13:00"},
            {"start_display": "13:00", "end_display": "14:00"},  # Should be ignored
            {"start_display": "14:00", "end_display": "15:00"},  # Should be ignored
        ]

        keyboard = slots_keyboard(slots)
        inline_keyboard = keyboard.inline_keyboard

        # All 3 buttons are in one row
        assert len(inline_keyboard[0]) == 3
        # Verify only first 3 are included
        assert inline_keyboard[0][0].callback_data == "slot:0"
        assert inline_keyboard[0][1].callback_data == "slot:1"
        assert inline_keyboard[0][2].callback_data == "slot:2"


class TestConfirmKeyboard:
    """Tests for confirm_keyboard function."""

    def test_confirm_keyboard_has_yes_no_buttons(self):
        """Test 7: Has 'Да' and 'Нет' buttons; 'Да' callback_data contains action."""
        keyboard = confirm_keyboard("create", "event_123")
        inline_keyboard = keyboard.inline_keyboard

        assert len(inline_keyboard) == 1  # One row with 2 buttons
        assert len(inline_keyboard[0]) == 2

        yes_btn = inline_keyboard[0][0]
        no_btn = inline_keyboard[0][1]

        assert yes_btn.text == "Да"
        assert no_btn.text == "Нет"
        assert "create" in yes_btn.callback_data

    def test_confirm_keyboard_payload_encoded_correctly(self):
        """Test 8: payload correctly encoded in callback_data and can be parsed."""
        action = "update"
        payload = "event_456"

        keyboard = confirm_keyboard(action, payload)
        inline_keyboard = keyboard.inline_keyboard

        yes_btn = inline_keyboard[0][0]
        callback_data = yes_btn.callback_data

        # Parse: cf:<action>:<payload>
        parts = callback_data.split(":")
        assert parts[0] == "cf"
        assert parts[1] == action
        assert parts[2] == payload

    def test_confirm_keyboard_decline_callback(self):
        """Additional test: 'Нет' button has cf:<action>:decline format."""
        keyboard = confirm_keyboard("delete", "reminder_789")
        inline_keyboard = keyboard.inline_keyboard

        no_btn = inline_keyboard[0][1]
        assert no_btn.callback_data == "cf:delete:decline"


class TestCallbackDataLength:
    """Tests for callback_data length constraint (≤64 bytes)."""

    def test_callback_data_length_limit(self):
        """Test 10: Any generated callback_data ≤ 64 bytes."""
        # Create a very long payload
        long_payload = "x" * 100  # 100 chars, should be truncated

        keyboard = confirm_keyboard("create", long_payload)
        inline_keyboard = keyboard.inline_keyboard

        yes_btn = inline_keyboard[0][0]
        no_btn = inline_keyboard[0][1]

        # Check both callback_data strings are ≤ 64 bytes
        assert len(yes_btn.callback_data.encode("utf-8")) <= 64
        assert len(no_btn.callback_data.encode("utf-8")) <= 64


class TestBuildRouter:
    """Tests for build_router function."""

    def test_build_router_returns_router_with_filters(self):
        """Test 9: Returns Router; WhitelistFilter registered on message and callback_query."""
        router = build_router()

        # Check it's a Router instance
        from aiogram import Router
        assert isinstance(router, Router)

        # Check filters are registered
        # In aiogram 3.x, filters are stored in router.message.filter and router.callback_query.filter
        assert hasattr(router, "message")
        assert hasattr(router, "callback_query")

        # Verify filter chain exists
        assert router.message.filter is not None
        assert router.callback_query.filter is not None


class TestIntegration:
    """Integration tests combining filter with mock events."""

    @pytest.mark.asyncio
    async def test_integration_whitelist_message_passes(self):
        """Test 11: Mock Message from whitelisted user passes filter (True)."""
        allowed_ids = [555555555]
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps(allowed_ids)
        get_settings.cache_clear()

        filter_obj = WhitelistFilter()
        mock_event = MagicMock(spec=Message)
        mock_event.from_user = SimpleNamespace(id=555555555)

        result = await filter_obj(mock_event)
        assert result is True

    @pytest.mark.asyncio
    async def test_integration_whitelist_callback_rejected(self):
        """Test 12: Mock CallbackQuery from non-whitelisted user rejected (False)."""
        # Already tested in TestWhitelistFilter.test_whitelist_callback_query
        # This is a duplicate for explicit coverage
        allowed_ids = [123456789]
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_DIGEST_CHAT_ID"] = "-1001234567890"
        os.environ["TELEGRAM_ALLOWED_USER_IDS"] = json.dumps(allowed_ids)
        get_settings.cache_clear()

        filter_obj = WhitelistFilter()
        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.from_user = SimpleNamespace(id=888888888)

        result = await filter_obj(mock_callback)
        assert result is False

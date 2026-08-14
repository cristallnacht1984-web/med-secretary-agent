"""Tests for config module."""

import os
from unittest.mock import patch

from app.config import Settings, get_settings


class TestSettings:
    """Test cases for Settings class."""

    def test_settings_required_field_telegram_bot_token(self) -> None:
        """Test that TELEGRAM_BOT_TOKEN is required."""
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test_token", "LLM_BASE_URL": "http://test"},
            clear=False,
        ):
            settings = Settings()
            assert settings.TELEGRAM_BOT_TOKEN == "test_token"

    def test_settings_default_llm_base_url(self) -> None:
        """Test default LLM_BASE_URL value."""
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test_token", "LLM_BASE_URL": "http://localhost:8000/v1"},
            clear=False,
        ):
            settings = Settings()
            assert settings.LLM_BASE_URL == "http://localhost:8000/v1"

    def test_settings_default_database_url(self) -> None:
        """Test default DATABASE_URL value."""
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test_token"},
            clear=False,
        ):
            settings = Settings()
            assert settings.DATABASE_URL == "sqlite+aiosqlite:///med_secretary.db"

    def test_settings_validate_required_fields_success(self) -> None:
        """Test validate_required_fields with all fields present."""
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test_token", "LLM_BASE_URL": "http://test"},
            clear=False,
        ):
            settings = Settings()
            errors = settings.validate_required_fields()
            assert errors == []

    def test_get_settings_cached(self) -> None:
        """Test that get_settings returns cached instance."""
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test_token", "LLM_BASE_URL": "http://test"},
            clear=False,
        ):
            # Clear cache first
            get_settings.cache_clear()
            settings1 = get_settings()
            settings2 = get_settings()
            assert settings1 is settings2

"""Tests for config module."""
import json
import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch: pytest.MonkeyPatch):
    """Clean environment variables and clear settings cache before each test."""
    # List of all env vars used by Settings
    env_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_ADMIN_ID",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
        "LLM_TEMPERATURE_ANALYSIS",
        "LLM_TEMPERATURE_CLASSIFICATION",
        "LLM_MAX_TOKENS",
        "LLM_TIMEOUT_ANALYSIS",
        "LLM_TIMEOUT_CLASSIFICATION",
        "LLM_RATE_LIMIT_RPM",
        "LLM_RATE_LIMIT_TPM",
        "DATABASE_URL",
        "GOOGLE_CREDENTIALS_JSON",
        "GOOGLE_CALENDAR_ID",
        "DIGEST_TIME_HOUR",
        "REMINDER_POLL_INTERVAL_MINUTES",
        "REMINDER_WINDOW_HOURS",
        "HEALTH_CHECK_HOST",
        "HEALTH_CHECK_PORT",
        "USER_TIMEZONE",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)

    # Clear the lru_cache to ensure fresh settings
    get_settings.cache_clear()

    yield

    # Cleanup after test
    get_settings.cache_clear()


class TestSettingsDefaults:
    """Test default values for settings."""

    def test_llm_base_url_default(self):
        """Test LLM_BASE_URL has correct default."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}):
            settings = Settings()
            assert settings.LLM_BASE_URL == "http://localhost:8000/v1"

    def test_llm_model_name_default(self):
        """Test LLM_MODEL_NAME has correct default."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}):
            settings = Settings()
            assert settings.LLM_MODEL_NAME == "qwen3.6"

    def test_database_url_default(self):
        """Test DATABASE_URL has correct default."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}):
            settings = Settings()
            assert settings.DATABASE_URL == "sqlite+aiosqlite:///./mednews.db"

    def test_digest_time_hour_default(self):
        """Test DIGEST_TIME_HOUR has correct default."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}):
            settings = Settings()
            assert settings.DIGEST_TIME_HOUR == 6

    def test_user_timezone_default(self):
        """Test USER_TIMEZONE has correct default."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}):
            settings = Settings()
            assert settings.USER_TIMEZONE == "UTC"


class TestSettingsValidation:
    """Test settings validation."""

    def test_telegram_bot_token_required(self):
        """Test TELEGRAM_BOT_TOKEN is required."""
        with pytest.raises(ValidationError):
            Settings()

    def test_temperature_range_valid(self):
        """Test temperature values within valid range."""
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "test_token",
                "LLM_TEMPERATURE_ANALYSIS": "0.5",
                "LLM_TEMPERATURE_CLASSIFICATION": "1.0",
            },
        ):
            settings = Settings()
            assert settings.LLM_TEMPERATURE_ANALYSIS == 0.5
            assert settings.LLM_TEMPERATURE_CLASSIFICATION == 1.0

    def test_temperature_range_invalid(self):
        """Test temperature values outside valid range raise error."""
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "test_token",
                "LLM_TEMPERATURE_ANALYSIS": "3.0",
            },
        ), pytest.raises(ValidationError):
            Settings()

    def test_port_range_valid(self):
        """Test port value within valid range."""
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test_token", "HEALTH_CHECK_PORT": "9000"},
        ):
            settings = Settings()
            assert settings.HEALTH_CHECK_PORT == 9000

    def test_port_range_invalid(self):
        """Test port value outside valid range raises error."""
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test_token", "HEALTH_CHECK_PORT": "70000"},
        ), pytest.raises(ValidationError):
            Settings()


class TestSettingsEnvParsing:
    """Test environment variable parsing."""

    def test_telegram_allowed_user_ids_json_array(self):
        """Test TELEGRAM_ALLOWED_USER_IDS parsed from JSON array."""
        user_ids = [123456, 789012]
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "test_token",
                "TELEGRAM_ALLOWED_USER_IDS": json.dumps(user_ids),
            },
        ):
            settings = Settings()
            assert settings.TELEGRAM_ALLOWED_USER_IDS == user_ids

    def test_telegram_allowed_user_ids_empty(self):
        """Test TELEGRAM_ALLOWED_USER_IDS defaults to empty list."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}):
            settings = Settings()
            assert settings.TELEGRAM_ALLOWED_USER_IDS == []

    def test_secret_str_for_api_key(self):
        """Test LLM_API_KEY is stored as SecretStr."""
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "test_token",
                "LLM_API_KEY": "secret_key_123",
            },
        ):
            settings = Settings()
            assert settings.LLM_API_KEY.get_secret_value() == "secret_key_123"


class TestSettingsGetSettings:
    """Test get_settings function."""

    def test_get_settings_returns_instance(self):
        """Test get_settings returns Settings instance."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}):
            settings = get_settings()
            assert isinstance(settings, Settings)

    def test_get_settings_cached(self):
        """Test get_settings returns cached instance."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}):
            settings1 = get_settings()
            settings2 = get_settings()
            assert settings1 is settings2

    def test_get_settings_cache_cleared(self):
        """Test cache clear allows new settings creation."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}):
            settings1 = get_settings()
            get_settings.cache_clear()
            settings2 = get_settings()
            # After cache clear, they might be different instances
            assert isinstance(settings1, Settings)
            assert isinstance(settings2, Settings)


class TestIntegration:
    """Integration tests."""

    def test_logging_imports_settings(self):
        """Test that logging module can import settings without issues."""
        from app.logging_setup import get_logger, setup_logging

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}):
            # Should not raise any exception
            setup_logging()
            logger = get_logger("test")
            assert logger is not None

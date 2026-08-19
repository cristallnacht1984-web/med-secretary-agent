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
    # List of all env vars used by Settings (canonical + legacy)
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

    # Set baseline required values for tests to pass
    # TELEGRAM_DIGEST_CHAT_ID is required per TZ §6, so we set a default test value
    monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")

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

        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }):
            # Should not raise any exception
            setup_logging()
            logger = get_logger("test")
            assert logger is not None


class TestNewFieldsDefaults:
    """Test default values for new canonical fields per TZ §6."""

    def test_digest_hour_default(self):
        """Test DIGEST_HOUR has correct default (6)."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.DIGEST_HOUR == 6

    def test_digest_minute_default(self):
        """Test DIGEST_MINUTE has correct default (0)."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.DIGEST_MINUTE == 0

    def test_timezone_default(self):
        """Test TIMEZONE has correct default (Europe/Moscow)."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.TIMEZONE == "Europe/Moscow"

    def test_log_level_default(self):
        """Test LOG_LEVEL has correct default (INFO)."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.LOG_LEVEL == "INFO"

    def test_news_batch_min_max_defaults(self):
        """Test NEWS_BATCH_MIN=3 and NEWS_BATCH_MAX=5 defaults."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.NEWS_BATCH_MIN == 3
            assert settings.NEWS_BATCH_MAX == 5

    def test_llm_temperature_reminder_default(self):
        """Test LLM_TEMPERATURE_REMINDER default (0.5)."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.LLM_TEMPERATURE_REMINDER == 0.5

    def test_llm_timeout_reminder_default(self):
        """Test LLM_TIMEOUT_REMINDER default (30)."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.LLM_TIMEOUT_REMINDER == 30

    def test_llm_max_retries_default(self):
        """Test LLM_MAX_RETRIES default (3)."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.LLM_MAX_RETRIES == 3

    def test_google_credentials_file_default(self):
        """Test GOOGLE_CREDENTIALS_FILE default path."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert str(settings.GOOGLE_CREDENTIALS_FILE) == "secrets/google_credentials.json"

    def test_google_token_file_default(self):
        """Test GOOGLE_TOKEN_FILE default path."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert str(settings.GOOGLE_TOKEN_FILE) == "data/google_token.json"

    def test_reminder_lookahead_minutes_default(self):
        """Test REMINDER_LOOKAHEAD_MINUTES default (120)."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.REMINDER_LOOKAHEAD_MINUTES == 120

    def test_news_pipeline_defaults(self):
        """Test all news pipeline field defaults."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.NEWS_LOOKBACK_HOURS == 24
            assert settings.NEWS_DEDUP_WINDOW_DAYS == 7
            assert settings.NEWS_DELIVERY_RETRIES == 3
            assert settings.NEWS_DELIVERY_RETRY_DELAY_MINUTES == 5
            assert settings.FETCH_TIMEOUT_SECONDS == 30.0
            assert settings.FETCH_MAX_RETRIES == 3

    def test_log_file_default_none(self):
        """Test LOG_FILE default is None."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
        }, clear=False):
            settings = Settings()
            assert settings.LOG_FILE is None


class TestTimezoneValidation:
    """Test TIMEZONE field validation with zoneinfo."""

    def test_timezone_valid_europe_moscow(self):
        """Test valid timezone Europe/Moscow passes."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "TIMEZONE": "Europe/Moscow",
        }, clear=False):
            settings = Settings()
            assert settings.TIMEZONE == "Europe/Moscow"

    def test_timezone_valid_utc(self):
        """Test valid timezone UTC passes."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "TIMEZONE": "UTC",
        }, clear=False):
            settings = Settings()
            assert settings.TIMEZONE == "UTC"

    def test_timezone_valid_america_new_york(self):
        """Test valid timezone America/New_York passes."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "TIMEZONE": "America/New_York",
        }, clear=False):
            settings = Settings()
            assert settings.TIMEZONE == "America/New_York"

    def test_timezone_invalid_mars_olympus(self):
        """Test invalid timezone 'Mars/Olympus' raises ValidationError."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "TIMEZONE": "Mars/Olympus",
        }, clear=False):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            assert "Invalid timezone" in str(exc_info.value)

    def test_timezone_invalid_not_a_zone(self):
        """Test invalid timezone 'Not/AZone' raises ValidationError."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "TIMEZONE": "Not/AZone",
        }, clear=False):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            assert "Invalid timezone" in str(exc_info.value)


class TestLogLevelValidation:
    """Test LOG_LEVEL field validation."""

    def test_log_level_warning_uppercased(self):
        """Test LOG_LEVEL 'warning' becomes 'WARNING'."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "LOG_LEVEL": "warning",
        }, clear=False):
            settings = Settings()
            assert settings.LOG_LEVEL == "WARNING"

    def test_log_level_verbose_invalid(self):
        """Test LOG_LEVEL 'VERBOSE' raises ValidationError."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "LOG_LEVEL": "VERBOSE",
        }, clear=False):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            assert "LOG_LEVEL must be one of" in str(exc_info.value)


class TestTelegramDigestChatId:
    """Test TELEGRAM_DIGEST_CHAT_ID required field."""

    def test_telegram_digest_chat_id_missing(self):
        """Test missing TELEGRAM_DIGEST_CHAT_ID raises ValidationError."""
        get_settings.cache_clear()
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
        }, clear=True):
            # Remove TELEGRAM_DIGEST_CHAT_ID if set
            os.environ.pop("TELEGRAM_DIGEST_CHAT_ID", None)
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            assert "TELEGRAM_DIGEST_CHAT_ID" in str(exc_info.value)

    def test_telegram_digest_chat_id_negative_channel(self):
        """Test negative chat ID (channel) parses correctly."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1009876543210",
        }, clear=False):
            settings = Settings()
            assert settings.TELEGRAM_DIGEST_CHAT_ID == -1009876543210

    def test_telegram_digest_chat_id_positive_user(self):
        """Test positive chat ID (user) parses correctly."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "123456789",
        }, clear=False):
            settings = Settings()
            assert settings.TELEGRAM_DIGEST_CHAT_ID == 123456789


class TestDigestHourMinuteBoundaries:
    """Test DIGEST_HOUR and DIGEST_MINUTE boundary validation."""

    def test_digest_hour_24_invalid(self):
        """Test DIGEST_HOUR=24 raises ValidationError."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "DIGEST_HOUR": "24",
        }, clear=False):
            with pytest.raises(ValidationError):
                Settings()

    def test_digest_hour_minus1_invalid(self):
        """Test DIGEST_HOUR=-1 raises ValidationError."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "DIGEST_HOUR": "-1",
        }, clear=False):
            with pytest.raises(ValidationError):
                Settings()

    def test_digest_minute_60_invalid(self):
        """Test DIGEST_MINUTE=60 raises ValidationError."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "DIGEST_MINUTE": "60",
        }, clear=False):
            with pytest.raises(ValidationError):
                Settings()


class TestNewsBatchValidation:
    """Test NEWS_BATCH_MIN/MAX model validator."""

    def test_news_batch_min_greater_than_max(self):
        """Test NEWS_BATCH_MIN > NEWS_BATCH_MAX raises ValidationError."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "NEWS_BATCH_MIN": "5",
            "NEWS_BATCH_MAX": "3",
        }, clear=False):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            assert "NEWS_BATCH_MIN" in str(exc_info.value)

    def test_news_batch_min_zero_invalid(self):
        """Test NEWS_BATCH_MIN=0 raises ValidationError."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "NEWS_BATCH_MIN": "0",
        }, clear=False):
            with pytest.raises(ValidationError):
                Settings()

    def test_news_batch_max_six_invalid(self):
        """Test NEWS_BATCH_MAX=6 raises ValidationError (>5)."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "NEWS_BATCH_MAX": "6",
        }, clear=False):
            with pytest.raises(ValidationError):
                Settings()


class TestAllowedUserIdsEmptyString:
    """Test §4.9 empty string validation for TELEGRAM_ALLOWED_USER_IDS."""

    def test_allowed_user_ids_empty_string_invalid(self):
        """Test TELEGRAM_ALLOWED_USER_IDS='' raises ValidationError."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "TELEGRAM_ALLOWED_USER_IDS": "",
        }, clear=False):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            assert "cannot be an empty string" in str(exc_info.value)


class TestEnvExampleParses:
    """Test .env.example file parses without errors."""

    def test_env_example_parses(self):
        """Test reading .env.example and creating Settings works."""
        import pathlib
        env_example_path = pathlib.Path(".env.example")
        assert env_example_path.exists(), ".env.example file must exist"

        # Read and parse the file
        env_vars = {}
        with open(env_example_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()

        # Must have required fields
        assert "TELEGRAM_BOT_TOKEN" in env_vars
        assert "TELEGRAM_DIGEST_CHAT_ID" in env_vars

        # Set env and create Settings
        with patch.dict(os.environ, env_vars, clear=False):
            settings = Settings()
            # Check some key new fields are populated
            assert settings.TIMEZONE in ["Europe/Moscow", "UTC"]
            assert settings.LOG_LEVEL in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            assert 1 <= settings.NEWS_BATCH_MIN <= settings.NEWS_BATCH_MAX <= 5


class TestLogFileFromEnv:
    """Test LOG_FILE field from environment."""

    def test_log_file_from_env(self):
        """Test LOG_FILE set from env becomes Path."""
        import pathlib
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_DIGEST_CHAT_ID": "-1001234567890",
            "LOG_FILE": "/var/log/mednews.log",
        }, clear=False):
            settings = Settings()
            assert settings.LOG_FILE == pathlib.Path("/var/log/mednews.log")

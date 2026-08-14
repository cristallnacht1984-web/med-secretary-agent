"""Tests for configuration module."""


import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch):
    """Clean environment variables and settings cache before each test.

    This fixture runs automatically before every test to ensure isolation.
    It removes all Settings-related env vars and clears the get_settings cache.
    """
    # List of all environment variable names used by Settings
    env_vars = [
        "APP_NAME",
        "DEBUG",
        "TIMEZONE",
        "LOG_LEVEL",
        "LOG_FILE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_DIGEST_CHAT_ID",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_ALLOWED_USER_IDS",
        "DATABASE_URL",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
        "LLM_MAX_TOKENS",
        "LLM_TIMEOUT_ANALYSIS",
        "LLM_TIMEOUT_CLASSIFICATION",
        "LLM_TIMEOUT_REMINDER",
        "LLM_TEMPERATURE_ANALYSIS",
        "LLM_TEMPERATURE_CLASSIFICATION",
        "LLM_TEMPERATURE_REMINDER",
        "LLM_RATE_LIMIT_RPM",
        "LLM_RATE_LIMIT_TPM",
        "LLM_MAX_RETRIES",
        "DIGEST_HOUR",
        "DIGEST_MINUTE",
        "NEWS_LOOKBACK_HOURS",
        "NEWS_DEDUP_WINDOW_DAYS",
        "NEWS_BATCH_MIN",
        "NEWS_BATCH_MAX",
        "NEWS_DELIVERY_RETRIES",
        "NEWS_DELIVERY_RETRY_DELAY_MINUTES",
        "FETCH_TIMEOUT_SECONDS",
        "FETCH_MAX_RETRIES",
        "GOOGLE_CREDENTIALS_FILE",
        "GOOGLE_TOKEN_FILE",
        "GOOGLE_CALENDAR_ID",
        "REMINDER_POLL_INTERVAL_MINUTES",
        "REMINDER_LOOKAHEAD_MINUTES",
    ]

    # Remove all env vars
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)

    # Clear the lru_cache
    from app.config import get_settings
    get_settings.cache_clear()

    yield

    # Cleanup after test (optional, but good practice)
    get_settings.cache_clear()


class TestConfigDefaults:
    """Test default values when only required env vars are set."""

    def test_defaults_with_required_only(self, monkeypatch):
        """Test that defaults apply when only required variables are set."""
        # Set only required variables
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")

        from app.config import get_settings
        settings = get_settings()

        # LLM defaults
        assert settings.LLM_MODEL_NAME == "qwen3.6"
        assert settings.LLM_RATE_LIMIT_RPM == 60
        assert settings.LLM_RATE_LIMIT_TPM == 100000
        assert settings.LLM_TIMEOUT_ANALYSIS == 120.0
        assert settings.LLM_TIMEOUT_CLASSIFICATION == 30.0
        assert settings.LLM_TIMEOUT_REMINDER == 30.0
        assert settings.LLM_TEMPERATURE_ANALYSIS == 0.3
        assert settings.LLM_TEMPERATURE_CLASSIFICATION == 0.3
        assert settings.LLM_TEMPERATURE_REMINDER == 0.5

        # Digest defaults
        assert settings.NEWS_BATCH_MIN == 3
        assert settings.NEWS_BATCH_MAX == 5
        assert settings.DIGEST_HOUR == 6
        assert settings.NEWS_DEDUP_WINDOW_DAYS == 7
        assert settings.NEWS_LOOKBACK_HOURS == 24

        # Reminders defaults
        assert settings.REMINDER_POLL_INTERVAL_MINUTES == 30
        assert settings.REMINDER_LOOKAHEAD_MINUTES == 120


class TestRequiredVariables:
    """Test that required variables raise ValidationError when missing."""

    def test_missing_telegram_bot_token(self, monkeypatch):
        """Test ValidationError when TELEGRAM_BOT_TOKEN is missing."""
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")

        from app.config import get_settings

        with pytest.raises(ValidationError):
            get_settings()

    def test_missing_telegram_digest_chat_id(self, monkeypatch):
        """Test ValidationError when TELEGRAM_DIGEST_CHAT_ID is missing."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")

        from app.config import get_settings

        with pytest.raises(ValidationError):
            get_settings()

    def test_missing_telegram_admin_id(self, monkeypatch):
        """Test ValidationError when TELEGRAM_ADMIN_ID is missing."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")

        from app.config import get_settings

        with pytest.raises(ValidationError):
            get_settings()

    def test_missing_telegram_allowed_user_ids(self, monkeypatch):
        """Test ValidationError when TELEGRAM_ALLOWED_USER_IDS is missing."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")

        from app.config import get_settings

        with pytest.raises(ValidationError):
            get_settings()


class TestEnvOverride:
    """Test that environment variables override defaults."""

    def test_custom_values_applied(self, monkeypatch):
        """Test that custom env values are applied correctly."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "custom_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-999888777")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "999888777")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[1, 2, 3]")

        monkeypatch.setenv("APP_NAME", "Custom App Name")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("TIMEZONE", "America/New_York")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        monkeypatch.setenv("LLM_MODEL_NAME", "custom-model")
        monkeypatch.setenv("LLM_RATE_LIMIT_RPM", "100")
        monkeypatch.setenv("LLM_MAX_TOKENS", "8192")

        from app.config import get_settings
        settings = get_settings()

        assert settings.APP_NAME == "Custom App Name"
        assert settings.DEBUG is True
        assert settings.TIMEZONE == "America/New_York"
        assert settings.LOG_LEVEL == "DEBUG"
        assert settings.LLM_MODEL_NAME == "custom-model"
        assert settings.LLM_RATE_LIMIT_RPM == 100
        assert settings.LLM_MAX_TOKENS == 8192


class TestTimezoneValidation:
    """Test timezone validation."""

    def test_invalid_timezone(self, monkeypatch):
        """Test that invalid timezone raises ValidationError."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
        monkeypatch.setenv("TIMEZONE", "Mars/Olympus")

        from app.config import get_settings

        with pytest.raises(ValidationError) as exc_info:
            get_settings()

        assert "timezone" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()

    def test_valid_timezones(self, monkeypatch):
        """Test various valid timezones."""
        valid_tz = ["Europe/Moscow", "UTC", "America/New_York", "Asia/Tokyo"]

        for tz in valid_tz:
            monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
            monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
            monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
            monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
            monkeypatch.setenv("TIMEZONE", tz)

            from app.config import get_settings
            get_settings.cache_clear()
            settings = get_settings()
            assert settings.TIMEZONE == tz


class TestLogLevelValidation:
    """Test log level validation."""

    def test_invalid_log_level(self, monkeypatch):
        """Test that invalid log level raises ValidationError."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
        monkeypatch.setenv("LOG_LEVEL", "TRACE")

        from app.config import get_settings

        with pytest.raises(ValidationError) as exc_info:
            get_settings()

        err_msg = str(exc_info.value).lower()
        assert "log_level" in err_msg or "invalid" in err_msg

    def test_log_level_case_insensitive(self, monkeypatch):
        """Test that log level is case insensitive and normalized to upper."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
        monkeypatch.setenv("LOG_LEVEL", "debug")

        from app.config import get_settings
        settings = get_settings()

        assert settings.LOG_LEVEL == "DEBUG"


class TestNewsBatchValidation:
    """Test news batch constraints validation."""

    def test_batch_min_greater_than_max(self, monkeypatch):
        """Test ValidationError when NEWS_BATCH_MIN > NEWS_BATCH_MAX."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
        monkeypatch.setenv("NEWS_BATCH_MIN", "5")
        monkeypatch.setenv("NEWS_BATCH_MAX", "3")

        from app.config import get_settings

        with pytest.raises(ValidationError) as exc_info:
            get_settings()

        assert "batch" in str(exc_info.value).lower()

    def test_batch_min_less_than_one(self, monkeypatch):
        """Test ValidationError when NEWS_BATCH_MIN < 1."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
        monkeypatch.setenv("NEWS_BATCH_MIN", "0")

        from app.config import get_settings

        with pytest.raises(ValidationError):
            get_settings()

    def test_batch_max_greater_than_five(self, monkeypatch):
        """Test ValidationError when NEWS_BATCH_MAX > 5."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
        monkeypatch.setenv("NEWS_BATCH_MAX", "10")

        from app.config import get_settings

        with pytest.raises(ValidationError):
            get_settings()


class TestDigestHourValidation:
    """Test digest hour validation."""

    def test_digest_hour_24(self, monkeypatch):
        """Test ValidationError when DIGEST_HOUR = 24."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
        monkeypatch.setenv("DIGEST_HOUR", "24")

        from app.config import get_settings

        with pytest.raises(ValidationError):
            get_settings()

    def test_digest_hour_valid_range(self, monkeypatch):
        """Test valid digest hours 0-23."""
        for hour in [0, 6, 12, 18, 23]:
            monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
            monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
            monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
            monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
            monkeypatch.setenv("DIGEST_HOUR", str(hour))

            from app.config import get_settings
            get_settings.cache_clear()
            settings = get_settings()
            assert settings.DIGEST_HOUR == hour


class TestSecretMasking:
    """Test that secrets are properly masked."""

    def test_secret_str_masked(self, monkeypatch):
        """Test that SecretStr fields are masked in string representation."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super_secret_token_12345")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")

        from app.config import get_settings
        settings = get_settings()

        # SecretStr should be masked
        assert str(settings.TELEGRAM_BOT_TOKEN) == "**********"


class TestEnvFileLoading:
    """Test loading settings from .env file."""

    def test_load_from_env_file(self, tmp_path):
        """Test that Settings loads values from specified .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("""
TELEGRAM_BOT_TOKEN=from_file_token
TELEGRAM_DIGEST_CHAT_ID=-111222333
TELEGRAM_ADMIN_ID=111222333
TELEGRAM_ALLOWED_USER_IDS=[1,2]
APP_NAME=From Env File App
LLM_MODEL_NAME=custom-from-file
""")

        from app.config import Settings
        settings = Settings(_env_file=str(env_file))

        assert settings.TELEGRAM_BOT_TOKEN.get_secret_value() == "from_file_token"
        assert settings.APP_NAME == "From Env File App"
        assert settings.LLM_MODEL_NAME == "custom-from-file"


class TestAllowedUserIdsParsing:
    """Test TELEGRAM_ALLOWED_USER_IDS parsing."""

    def test_json_string_parsing(self, monkeypatch):
        """Test parsing JSON string to list[int]."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[1, 2, 3]")

        from app.config import get_settings
        settings = get_settings()

        assert settings.TELEGRAM_ALLOWED_USER_IDS == [1, 2, 3]
        assert all(isinstance(x, int) for x in settings.TELEGRAM_ALLOWED_USER_IDS)

    def test_empty_list_validation_error(self, monkeypatch):
        """Test ValidationError when allowed user IDs list is empty."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[]")

        from app.config import get_settings

        with pytest.raises(ValidationError) as exc_info:
            get_settings()

        assert "at least 1" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()

    def test_invalid_json_error(self, monkeypatch):
        """Test error when JSON is invalid."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "not-json")

        from app.config import get_settings

        with pytest.raises((ValidationError, Exception)):
            get_settings()


class TestIntegration:
    """Integration tests for logging and config."""

    def test_logging_imports_settings(self, monkeypatch):
        """logging_setup.py should successfully import get_settings from app.config."""
        # Set required env vars for settings to work
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")

        # Force reload to trigger the import branch
        import importlib

        from app import logging_setup
        from app.config import get_settings
        importlib.reload(logging_setup)

        settings = get_settings()
        assert settings.LOG_LEVEL == "INFO"

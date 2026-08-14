"""Тесты для модуля конфигурации app.config."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings

# Список всех env-переменных, которые может читать Settings
ALL_SETTINGS_ENV_VARS = [
    "APP_NAME",
    "DEBUG",
    "TIMEZONE",
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
    "LOG_LEVEL",
    "LOG_FILE",
]


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Гарантирует чистую среду для каждого теста.

    Удаляет все возможные env-переменные Settings из ОС и очищает кэш get_settings().
    """
    # 1. Удаляем ВСЕ возможные env-переменные Settings из ОС
    for var in ALL_SETTINGS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # 2. Чистим кэш get_settings()
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Устанавливает минимальный набор обязательных переменных для валидных настроек."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "123456")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "789012")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[1, 2]")


class TestDefaults:
    """Тесты значений по умолчанию."""

    def test_defaults_with_required_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Проверка значений по умолчанию при заданных только обязательных полях."""
        _set_required_env(monkeypatch)
        settings = get_settings()

        assert settings.LLM_MODEL_NAME == "qwen3.6"
        assert str(settings.LLM_BASE_URL) == "http://localhost:8000/v1"
        assert settings.LLM_RATE_LIMIT_RPM == 60
        assert settings.LLM_RATE_LIMIT_TPM == 100000
        assert settings.LLM_TIMEOUT_ANALYSIS == 120.0
        assert settings.LLM_TIMEOUT_CLASSIFICATION == 30.0
        assert settings.LLM_TIMEOUT_REMINDER == 30.0
        assert settings.LLM_TEMPERATURE_ANALYSIS == 0.3
        assert settings.LLM_TEMPERATURE_CLASSIFICATION == 0.3
        assert settings.LLM_TEMPERATURE_REMINDER == 0.5
        assert settings.NEWS_BATCH_MIN == 3
        assert settings.NEWS_BATCH_MAX == 5
        assert settings.DIGEST_HOUR == 6
        assert settings.NEWS_DEDUP_WINDOW_DAYS == 7
        assert settings.NEWS_LOOKBACK_HOURS == 24
        assert settings.REMINDER_POLL_INTERVAL_MINUTES == 30
        assert settings.REMINDER_LOOKAHEAD_MINUTES == 120
        assert settings.TIMEZONE == "Europe/Moscow"


class TestMissingRequired:
    """Тесты отсутствия обязательных полей."""

    def test_missing_telegram_bot_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Отсутствие TELEGRAM_BOT_TOKEN вызывает ValidationError."""
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "123456")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "789012")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[1, 2]")

        with pytest.raises(ValidationError):
            Settings()

    def test_missing_telegram_digest_chat_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Отсутствие TELEGRAM_DIGEST_CHAT_ID вызывает ValidationError."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "789012")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[1, 2]")

        with pytest.raises(ValidationError):
            Settings()


class TestOverrideViaEnv:
    """Тесты переопределения через env."""

    def test_llm_model_name_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Переопределение LLM_MODEL_NAME через env."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("LLM_MODEL_NAME", "custom-model")

        settings = get_settings()
        assert settings.LLM_MODEL_NAME == "custom-model"


class TestInvalidTimezone:
    """Тесты невалидного часового пояса."""

    def test_invalid_timezone_mars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Невалидный часовой пояс Mars/Olympus вызывает ValidationError."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("TIMEZONE", "Mars/Olympus")

        with pytest.raises(ValidationError):
            Settings()


class TestInvalidLogLevel:
    """Тесты невалидного уровня логирования."""

    def test_invalid_log_level_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Невалидный уровень логирования FATAL вызывает ValidationError."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("LOG_LEVEL", "FATAL")

        with pytest.raises(ValidationError):
            Settings()


class TestBatchBounds:
    """Тесты границ размера пакета новостей."""

    def test_min_greater_than_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """NEWS_BATCH_MIN > NEWS_BATCH_MAX вызывает ValidationError."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("NEWS_BATCH_MIN", "6")
        monkeypatch.setenv("NEWS_BATCH_MAX", "5")

        with pytest.raises(ValidationError):
            Settings()

    def test_min_less_than_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """NEWS_BATCH_MIN < 1 вызывает ValidationError."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("NEWS_BATCH_MIN", "0")
        monkeypatch.setenv("NEWS_BATCH_MAX", "3")

        with pytest.raises(ValidationError):
            Settings()

    def test_max_greater_than_five(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """NEWS_BATCH_MAX > 5 вызывает ValidationError."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("NEWS_BATCH_MIN", "3")
        monkeypatch.setenv("NEWS_BATCH_MAX", "6")

        with pytest.raises(ValidationError):
            Settings()


class TestDigestHour:
    """Тесты часа отправки дайджеста."""

    def test_digest_hour_24(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DIGEST_HOUR = 24 вызывает ValidationError."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("DIGEST_HOUR", "24")

        with pytest.raises(ValidationError):
            Settings()


class TestSecretMasking:
    """Тесты маскировки секретов."""

    def test_secret_str_masking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SecretStr маскирует значение в str() и repr()."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret-token-12345")

        settings = get_settings()

        # Проверка маскировки
        assert str(settings.TELEGRAM_BOT_TOKEN) == "**********"

        # Проверка, что исходное значение не встречается в repr
        repr_str = repr(settings)
        assert "super-secret-token-12345" not in repr_str


class TestLoadFromEnvFile:
    """Тесты загрузки из .env файла."""

    def test_load_from_env_file(self, tmp_path: Path) -> None:
        """Загрузка настроек из временного .env файла."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "TELEGRAM_BOT_TOKEN=file-bot-token\n"
            "TELEGRAM_DIGEST_CHAT_ID=999888\n"
            "TELEGRAM_ADMIN_ID=111222\n"
            "TELEGRAM_ALLOWED_USER_IDS=[3, 4]\n"
        )

        settings = Settings(_env_file=env_file)

        assert settings.TELEGRAM_BOT_TOKEN.get_secret_value() == "file-bot-token"
        assert settings.TELEGRAM_DIGEST_CHAT_ID == 999888


class TestAllowedUserIdsParsing:
    """Тесты парсинга TELEGRAM_ALLOWED_USER_IDS."""

    def test_json_string_array(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON-строка '[1, 2]' корректно парсится в list[int]."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[1, 2]")

        settings = get_settings()
        assert settings.TELEGRAM_ALLOWED_USER_IDS == [1, 2]

    def test_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Пустой список [] вызывает ValidationError."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[]")

        with pytest.raises(ValidationError):
            Settings()

    def test_non_json_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Строка '1' (не JSON) вызывает ValidationError."""
        _set_required_env(monkeypatch)
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1")

        with pytest.raises(ValidationError):
            Settings()

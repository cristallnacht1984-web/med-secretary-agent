"""Конфигурация приложения MedNews Secretary Agent.

Модуль содержит класс Settings для валидации и загрузки конфигурации
из переменных окружения и файла .env с использованием pydantic-settings.
"""

import functools
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения MedNews Secretary Agent.

    Все настройки загружаются из переменных окружения или файла .env.
    Имена полей соответствуют именам переменных окружения в верхнем регистре.

    Attributes:
        APP_NAME: Название приложения.
        DEBUG: Режим отладки.
        TIMEZONE: Часовой пояс для работы с датами.
        TELEGRAM_BOT_TOKEN: Токен Telegram-бота.
        TELEGRAM_DIGEST_CHAT_ID: ID чата для дайджеста.
        TELEGRAM_ADMIN_ID: ID администратора.
        TELEGRAM_ALLOWED_USER_IDS: Список разрешённых ID пользователей.
        DATABASE_URL: URL подключения к базе данных.
        LLM_BASE_URL: Базовый URL LLM API.
        LLM_API_KEY: API ключ для LLM.
        LLM_MODEL_NAME: Название модели LLM.
        LLM_MAX_TOKENS: Максимальное количество токенов для генерации.
        LLM_TIMEOUT_ANALYSIS: Таймаут для анализа новостей (секунды).
        LLM_TIMEOUT_CLASSIFICATION: Таймаут для классификации (секунды).
        LLM_TIMEOUT_REMINDER: Таймаут для напоминаний (секунды).
        LLM_TEMPERATURE_ANALYSIS: Температура для анализа новостей.
        LLM_TEMPERATURE_CLASSIFICATION: Температура для классификации.
        LLM_TEMPERATURE_REMINDER: Температура для напоминаний.
        LLM_RATE_LIMIT_RPM: Лимит запросов в минуту.
        LLM_RATE_LIMIT_TPM: Лимит токенов в минуту.
        LLM_MAX_RETRIES: Максимальное количество повторных попыток.
        DIGEST_HOUR: Час публикации дайджеста.
        DIGEST_MINUTE: Минута публикации дайджеста.
        NEWS_LOOKBACK_HOURS: Период lookback для новостей (часы).
        NEWS_DEDUP_WINDOW_DAYS: Окно дедупликации новостей (дни).
        NEWS_BATCH_MIN: Минимальный размер батча новостей.
        NEWS_BATCH_MAX: Максимальный размер батча новостей.
        NEWS_DELIVERY_RETRIES: Количество попыток доставки.
        NEWS_DELIVERY_RETRY_DELAY_MINUTES: Задержка между попытками доставки (минуты).
        FETCH_TIMEOUT_SECONDS: Таймаут fetching новостей (секунды).
        FETCH_MAX_RETRIES: Максимальное количество retry при fetch.
        GOOGLE_CREDENTIALS_FILE: Путь к файлу учётных данных Google.
        GOOGLE_TOKEN_FILE: Путь к файлу токена Google.
        GOOGLE_CALENDAR_ID: ID календаря Google.
        REMINDER_POLL_INTERVAL_MINUTES: Интервал опроса напоминаний (минуты).
        REMINDER_LOOKAHEAD_MINUTES: Горизонт планирования напоминаний (минуты).
        LOG_LEVEL: Уровень логирования.
        LOG_FILE: Путь к файлу логов (опционально).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== App Settings =====
    APP_NAME: str = "MedNews Secretary Agent"
    DEBUG: bool = False
    TIMEZONE: str = "Europe/Moscow"

    # ===== Telegram Settings =====
    TELEGRAM_BOT_TOKEN: SecretStr
    TELEGRAM_DIGEST_CHAT_ID: int
    TELEGRAM_ADMIN_ID: int
    TELEGRAM_ALLOWED_USER_IDS: list[int]

    # ===== Database Settings =====
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/med_secretary.db"

    # ===== LLM Settings =====
    LLM_BASE_URL: HttpUrl = "http://localhost:8000/v1"
    LLM_API_KEY: SecretStr = SecretStr("dummy")
    LLM_MODEL_NAME: str = "qwen3.6"
    LLM_MAX_TOKENS: int = Field(default=4096, gt=0)
    LLM_TIMEOUT_ANALYSIS: float = 120.0
    LLM_TIMEOUT_CLASSIFICATION: float = 30.0
    LLM_TIMEOUT_REMINDER: float = 30.0
    LLM_TEMPERATURE_ANALYSIS: float = 0.3
    LLM_TEMPERATURE_CLASSIFICATION: float = 0.3
    LLM_TEMPERATURE_REMINDER: float = 0.5
    LLM_RATE_LIMIT_RPM: int = Field(default=60, gt=0)
    LLM_RATE_LIMIT_TPM: int = Field(default=100000, gt=0)
    LLM_MAX_RETRIES: int = Field(default=3, ge=1)

    # ===== Digest Settings =====
    DIGEST_HOUR: int = Field(default=6, ge=0, le=23)
    DIGEST_MINUTE: int = Field(default=0, ge=0, le=59)
    NEWS_LOOKBACK_HOURS: int = 24
    NEWS_DEDUP_WINDOW_DAYS: int = 7
    NEWS_BATCH_MIN: int = 3
    NEWS_BATCH_MAX: int = 5
    NEWS_DELIVERY_RETRIES: int = 3
    NEWS_DELIVERY_RETRY_DELAY_MINUTES: int = 5
    FETCH_TIMEOUT_SECONDS: float = 30.0
    FETCH_MAX_RETRIES: int = 3

    # ===== Calendar Settings =====
    GOOGLE_CREDENTIALS_FILE: Path = Path("secrets/google_credentials.json")
    GOOGLE_TOKEN_FILE: Path = Path("data/google_token.json")
    GOOGLE_CALENDAR_ID: str = "primary"

    # ===== Reminders Settings =====
    REMINDER_POLL_INTERVAL_MINUTES: int = 30
    REMINDER_LOOKAHEAD_MINUTES: int = 120

    # ===== Logging Settings =====
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Path | None = None

    @field_validator("TIMEZONE")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Валидация часового пояса.

        Args:
            value: Строка с названием часового пояса.

        Returns:
            Проверенная строка часового пояса.

        Raises:
            ValueError: Если часовой пояс невалиден.
        """
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"Invalid timezone: {value}") from exc
        return value

    @field_validator("TELEGRAM_ALLOWED_USER_IDS", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, value: Any) -> list[int]:
        """Парсинг списка разрешённых ID пользователей.

        Args:
            value: Значение из переменной окружения (строка JSON или список).

        Returns:
            Список целочисленных ID пользователей.

        Raises:
            ValueError: Если значение пустое или невалидное.
        """
        if isinstance(value, list):
            result = value
        elif isinstance(value, str):
            try:
                result = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"TELEGRAM_ALLOWED_USER_IDS must be a valid JSON array, got: {value}"
                ) from exc
        else:
            raise ValueError(
                f"TELEGRAM_ALLOWED_USER_IDS must be a list or JSON string, got: {type(value)}"
            )

        if not result:
            raise ValueError("Whitelist cannot be empty")

        return [int(x) for x in result]

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Валидация уровня логирования.

        Args:
            value: Строка с уровнем логирования.

        Returns:
            Приведённая к верхнему регистру строка уровня логирования.

        Raises:
            ValueError: Если уровень логирования невалиден.
        """
        value = value.upper()
        allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if value not in allowed_levels:
            raise ValueError(
                f"Invalid LOG_LEVEL: {value}. Allowed: {', '.join(sorted(allowed_levels))}"
            )
        return value

    @model_validator(mode="after")
    def validate_batches(self) -> "Settings":
        """Валидация границ батчей новостей.

        Returns:
            Текущий экземпляр Settings.

        Raises:
            ValueError: Если границы батчей некорректны.
        """
        if not (1 <= self.NEWS_BATCH_MIN <= self.NEWS_BATCH_MAX <= 5):
            raise ValueError("NEWS_BATCH_MIN/MAX: 1 <= MIN <= MAX <= 5")
        return self


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает кэшированный экземпляр Settings (singleton).

    Returns:
        Кэшированный экземпляр Settings.
    """
    return Settings()

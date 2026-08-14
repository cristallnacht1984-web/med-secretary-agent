"""Configuration module for MedNews Secretary Agent.

Uses pydantic-settings for environment variable validation and management.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import (
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings are loaded from environment variables with UPPER_CASE names.
    Default values are provided where applicable. Secrets are masked in logs.

    Attributes:
        APP_NAME: Application name for logging and identification.
        DEBUG: Debug mode flag.
        TIMEZONE: Timezone for scheduling (validated via zoneinfo).
        LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        LOG_FILE: Optional path to log file.

        TELEGRAM_BOT_TOKEN: Telegram bot token (required, secret).
        TELEGRAM_DIGEST_CHAT_ID: Chat ID for digest delivery (required).
        TELEGRAM_ADMIN_ID: Admin user ID for notifications (required).
        TELEGRAM_ALLOWED_USER_IDS: List of allowed user IDs (required, min 1).

        DATABASE_URL: SQLAlchemy database URL.

        LLM_BASE_URL: Base URL for LLM API (OpenAI-compatible).
        LLM_API_KEY: API key for LLM service (secret).
        LLM_MODEL_NAME: Model name for inference.
        LLM_MAX_TOKENS: Maximum tokens for generation.
        LLM_TIMEOUT_ANALYSIS: Timeout for news analysis calls.
        LLM_TIMEOUT_CLASSIFICATION: Timeout for classification calls.
        LLM_TIMEOUT_REMINDER: Timeout for reminder calls.
        LLM_TEMPERATURE_ANALYSIS: Temperature for analysis.
        LLM_TEMPERATURE_CLASSIFICATION: Temperature for classification.
        LLM_TEMPERATURE_REMINDER: Temperature for reminders.
        LLM_RATE_LIMIT_RPM: Requests per minute limit.
        LLM_RATE_LIMIT_TPM: Tokens per minute limit.
        LLM_MAX_RETRIES: Maximum retry attempts.

        DIGEST_HOUR: Hour for daily digest (0-23).
        DIGEST_MINUTE: Minute for daily digest (0-59).
        NEWS_LOOKBACK_HOURS: Hours to look back for news.
        NEWS_DEDUP_WINDOW_DAYS: Days for deduplication window.
        NEWS_BATCH_MIN: Minimum batch size for news processing.
        NEWS_BATCH_MAX: Maximum batch size for news processing.
        NEWS_DELIVERY_RETRIES: Retries for digest delivery.
        NEWS_DELIVERY_RETRY_DELAY_MINUTES: Delay between delivery retries.
        FETCH_TIMEOUT_SECONDS: Timeout for RSS fetching.
        FETCH_MAX_RETRIES: Max retries for RSS fetching.

        GOOGLE_CREDENTIALS_FILE: Path to Google credentials JSON.
        GOOGLE_TOKEN_FILE: Path to Google OAuth token file.
        GOOGLE_CALENDAR_ID: Calendar ID for events.

        REMINDER_POLL_INTERVAL_MINUTES: Interval for reminder polling.
        REMINDER_LOOKAHEAD_MINUTES: How far ahead to check for reminders.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # =========================================================================
    # ПРИЛОЖЕНИЕ / APPLICATION
    # =========================================================================
    APP_NAME: str = Field(default="MedNews Secretary Agent", alias="app_name")
    DEBUG: bool = Field(default=False, alias="debug")
    TIMEZONE: str = Field(default="Europe/Moscow", alias="timezone")
    LOG_LEVEL: str = Field(default="INFO", alias="log_level")
    LOG_FILE: Path | None = Field(default=None, alias="log_file")

    # =========================================================================
    # TELEGRAM
    # =========================================================================
    TELEGRAM_BOT_TOKEN: SecretStr = Field(..., alias="telegram_bot_token")
    TELEGRAM_DIGEST_CHAT_ID: int = Field(..., alias="telegram_digest_chat_id")
    TELEGRAM_ADMIN_ID: int = Field(..., alias="telegram_admin_id")
    TELEGRAM_ALLOWED_USER_IDS: list[int] = Field(..., alias="telegram_allowed_user_ids")

    # =========================================================================
    # БАЗА ДАННЫХ / DATABASE
    # =========================================================================
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./data/med_secretary.db",
        alias="database_url",
    )

    # =========================================================================
    # LLM (Qwen 3.6 via OpenAI-compatible API)
    # =========================================================================
    LLM_BASE_URL: HttpUrl = Field(
        default="http://localhost:8000/v1",
        alias="llm_base_url",
    )
    LLM_API_KEY: SecretStr = Field(
        default=SecretStr("dummy"),
        alias="llm_api_key",
    )
    LLM_MODEL_NAME: str = Field(default="qwen3.6", alias="llm_model_name")
    LLM_MAX_TOKENS: int = Field(default=4096, gt=0, alias="llm_max_tokens")
    LLM_TIMEOUT_ANALYSIS: float = Field(
        default=120.0,
        alias="llm_timeout_analysis",
    )
    LLM_TIMEOUT_CLASSIFICATION: float = Field(
        default=30.0,
        alias="llm_timeout_classification",
    )
    LLM_TIMEOUT_REMINDER: float = Field(
        default=30.0,
        alias="llm_timeout_reminder",
    )
    LLM_TEMPERATURE_ANALYSIS: float = Field(
        default=0.3,
        alias="llm_temperature_analysis",
    )
    LLM_TEMPERATURE_CLASSIFICATION: float = Field(
        default=0.3,
        alias="llm_temperature_classification",
    )
    LLM_TEMPERATURE_REMINDER: float = Field(
        default=0.5,
        alias="llm_temperature_reminder",
    )
    LLM_RATE_LIMIT_RPM: int = Field(
        default=60,
        gt=0,
        alias="llm_rate_limit_rpm",
    )
    LLM_RATE_LIMIT_TPM: int = Field(
        default=100000,
        gt=0,
        alias="llm_rate_limit_tpm",
    )
    LLM_MAX_RETRIES: int = Field(
        default=3,
        ge=1,
        alias="llm_max_retries",
    )

    # =========================================================================
    # ДАЙДЖЕСТ / DIGEST
    # =========================================================================
    DIGEST_HOUR: int = Field(default=6, ge=0, le=23, alias="digest_hour")
    DIGEST_MINUTE: int = Field(default=0, ge=0, le=59, alias="digest_minute")
    NEWS_LOOKBACK_HOURS: int = Field(
        default=24,
        alias="news_lookback_hours",
    )
    NEWS_DEDUP_WINDOW_DAYS: int = Field(
        default=7,
        alias="news_dedup_window_days",
    )
    NEWS_BATCH_MIN: int = Field(default=3, alias="news_batch_min")
    NEWS_BATCH_MAX: int = Field(default=5, alias="news_batch_max")
    NEWS_DELIVERY_RETRIES: int = Field(
        default=3,
        alias="news_delivery_retries",
    )
    NEWS_DELIVERY_RETRY_DELAY_MINUTES: int = Field(
        default=5,
        alias="news_delivery_retry_delay_minutes",
    )
    FETCH_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        alias="fetch_timeout_seconds",
    )
    FETCH_MAX_RETRIES: int = Field(default=3, alias="fetch_max_retries")

    # =========================================================================
    # GOOGLE CALENDAR
    # =========================================================================
    GOOGLE_CREDENTIALS_FILE: Path = Field(
        default=Path("secrets/google_credentials.json"),
        alias="google_credentials_file",
    )
    GOOGLE_TOKEN_FILE: Path = Field(
        default=Path("data/google_token.json"),
        alias="google_token_file",
    )
    GOOGLE_CALENDAR_ID: str = Field(
        default="primary",
        alias="google_calendar_id",
    )

    # =========================================================================
    # НАПОМИНАНИЯ / REMINDERS
    # =========================================================================
    REMINDER_POLL_INTERVAL_MINUTES: int = Field(
        default=30,
        alias="reminder_poll_interval_minutes",
    )
    REMINDER_LOOKAHEAD_MINUTES: int = Field(
        default=120,
        alias="reminder_lookahead_minutes",
    )

    @field_validator("TIMEZONE")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate timezone using zoneinfo.ZoneInfo.

        Args:
            v: Timezone string (e.g., "Europe/Moscow").

        Returns:
            The validated timezone string.

        Raises:
            ValidationError: If timezone is not valid.
        """
        try:
            ZoneInfo(v)
        except Exception as e:
            raise ValueError(f"Invalid timezone: {v}") from e
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate and normalize log level.

        Args:
            v: Log level string.

        Returns:
            Uppercase log level string.

        Raises:
            ValueError: If log level is not valid.
        """
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_v = v.upper()
        if upper_v not in valid_levels:
            raise ValueError(
                f"Invalid log level: {v}. Must be one of {valid_levels}"
            )
        return upper_v

    @field_validator("TELEGRAM_ALLOWED_USER_IDS")
    @classmethod
    def parse_allowed_user_ids(cls, v: Any) -> list[int]:
        """Parse TELEGRAM_ALLOWED_USERIDS from JSON string or list.

        Args:
            v: Either a JSON string like "[1,2,3]" or a list of ints.

        Returns:
            List of allowed user IDs.

        Raises:
            ValueError: If parsing fails or list is empty.
        """
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"TELEGRAM_ALLOWED_USER_IDS must be valid JSON array: {v}"
                ) from e
            if not isinstance(parsed, list):
                raise ValueError(
                    f"TELEGRAM_ALLOWED_USER_IDS must be a JSON array, got {type(parsed)}"
                )
            v = parsed

        if not isinstance(v, list):
            raise ValueError(
                f"TELEGRAM_ALLOWED_USER_IDS must be a list, got {type(v)}"
            )

        if len(v) == 0:
            raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain at least 1 user ID")

        try:
            return [int(x) for x in v]
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"TELEGRAM_ALLOWED_USER_IDS must contain integers: {v}"
            ) from e

    @model_validator(mode="after")
    def validate_news_batch(self) -> "Settings":
        """Validate news batch constraints: 1 <= MIN <= MAX <= 5.

        Returns:
            The validated Settings instance.

        Raises:
            ValueError: If batch constraints are violated.
        """
        min_batch = self.NEWS_BATCH_MIN
        max_batch = self.NEWS_BATCH_MAX

        if min_batch < 1:
            raise ValueError(f"NEWS_BATCH_MIN must be >= 1, got {min_batch}")
        if max_batch > 5:
            raise ValueError(f"NEWS_BATCH_MAX must be <= 5, got {max_batch}")
        if min_batch > max_batch:
            raise ValueError(
                f"NEWS_BATCH_MIN ({min_batch}) must be <= NEWS_BATCH_MAX ({max_batch})"
            )

        return self


@lru_cache(maxsize=1)
def get_settings(_env_file: str | None = None) -> Settings:
    """Get cached application settings.

    Uses LRU cache to avoid re-parsing environment variables on every call.
    Pass _env_file to override the default .env file location.

    Args:
        _env_file: Optional path to .env file. If None, uses default.

    Returns:
        Settings instance with validated configuration.
    """
    if _env_file is not None:
        return Settings(_env_file=_env_file)
    return Settings()

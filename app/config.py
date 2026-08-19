"""Configuration module for MedNews Secretary Agent.

Canonical fields align with TZ.md §6. Legacy fields preserved for backward compatibility.

LEGACY → CANONICAL MAPPING (new modules MUST use canonical only):
- DIGEST_TIME_HOUR → DIGEST_HOUR + DIGEST_MINUTE
- USER_TIMEZONE → TIMEZONE
- GOOGLE_CREDENTIALS_JSON → GOOGLE_CREDENTIALS_FILE
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Telegram settings
    TELEGRAM_BOT_TOKEN: SecretStr = Field(
        ..., description="Telegram bot token"
    )
    TELEGRAM_ALLOWED_USER_IDS: Annotated[list[int], NoDecode] = Field(
        default_factory=list,
        description="List of allowed Telegram user IDs (JSON array)",
    )
    TELEGRAM_ADMIN_ID: int | None = Field(
        default=None, description="Admin Telegram user ID for critical notifications"
    )
    TELEGRAM_DIGEST_CHAT_ID: int = Field(
        ...,
        description=(
            "Telegram chat/channel ID for daily digest delivery "
            "(negative for channels)"
        ),
    )

    @field_validator("TELEGRAM_ALLOWED_USER_IDS", mode="before")
    @classmethod
    def handle_empty_allowed_user_ids(cls, v):
        """Reject empty string before JSON parsing (§4.9), then parse JSON."""
        if isinstance(v, str):
            if v.strip() == "":
                raise ValueError("TELEGRAM_ALLOWED_USER_IDS cannot be an empty string")
            return json.loads(v)
        return v

    # LLM settings
    LLM_BASE_URL: str = Field(
        default="http://localhost:8000/v1",
        description="OpenAI-compatible API base URL",
    )
    LLM_API_KEY: SecretStr = Field(
        default=SecretStr("dummy"),
        description="LLM API key",
    )
    LLM_MODEL_NAME: str = Field(
        default="qwen3.6",
        description="LLM model name",
    )
    LLM_TEMPERATURE_ANALYSIS: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="Temperature for analysis tasks",
    )
    LLM_TEMPERATURE_CLASSIFICATION: float = Field(
        default=0.5,
        ge=0.0,
        le=2.0,
        description="Temperature for classification tasks",
    )
    LLM_TEMPERATURE_REMINDER: float = Field(
        default=0.5,
        ge=0.0,
        le=2.0,
        description="Temperature for reminder tasks",
    )
    LLM_MAX_TOKENS: int = Field(
        default=4096,
        gt=0,
        description="Max tokens for LLM response",
    )
    LLM_TIMEOUT_ANALYSIS: int = Field(
        default=120,
        gt=0,
        description="Timeout in seconds for analysis calls",
    )
    LLM_TIMEOUT_CLASSIFICATION: int = Field(
        default=30,
        gt=0,
        description="Timeout in seconds for classification calls",
    )
    LLM_TIMEOUT_REMINDER: int = Field(
        default=30,
        gt=0,
        description="Timeout in seconds for reminder calls",
    )
    LLM_RATE_LIMIT_RPM: int = Field(
        default=60,
        gt=0,
        description="Rate limit requests per minute",
    )
    LLM_RATE_LIMIT_TPM: int = Field(
        default=100000,
        gt=0,
        description="Rate limit tokens per minute",
    )
    LLM_MAX_RETRIES: int = Field(
        default=3,
        ge=0,
        description="Max retries for LLM API calls",
    )

    # Database settings
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./mednews.db",
        description="Async database URL",
    )

    # Google Calendar settings (canonical - file-based)
    GOOGLE_CREDENTIALS_FILE: Path = Field(
        default=Path("secrets/google_credentials.json"),
        description="Path to Google OAuth credentials JSON file",
    )
    GOOGLE_TOKEN_FILE: Path = Field(
        default=Path("data/google_token.json"),
        description="Path to Google OAuth token cache file",
    )
    GOOGLE_CALENDAR_ID: str = Field(
        default="primary",
        description="Google Calendar ID to use",
    )
    # Legacy field for backward compatibility (GOOGLE_CREDENTIALS_JSON)
    GOOGLE_CREDENTIALS_JSON: str | None = Field(
        default=None,
        description=(
            "[LEGACY] Google OAuth credentials JSON string - "
            "use GOOGLE_CREDENTIALS_FILE instead"
        ),
    )

    # Scheduler settings (canonical - TZ §6)
    DIGEST_HOUR: int = Field(
        default=6,
        ge=0,
        le=23,
        description="Hour for daily digest (TZ aware)",
    )
    DIGEST_MINUTE: int = Field(
        default=0,
        ge=0,
        le=59,
        description="Minute for daily digest",
    )
    # Legacy field for backward compatibility
    DIGEST_TIME_HOUR: int = Field(
        default=6,
        ge=0,
        le=23,
        description="[LEGACY] Hour for daily digest - use DIGEST_HOUR instead",
    )
    REMINDER_POLL_INTERVAL_MINUTES: int = Field(
        default=30,
        gt=0,
        description="Interval in minutes for reminder polling",
    )
    REMINDER_LOOKAHEAD_MINUTES: int = Field(
        default=120,
        gt=0,
        description="Minutes ahead to check for reminders",
    )
    # Legacy field for backward compatibility
    REMINDER_WINDOW_HOURS: int = Field(
        default=2,
        gt=0,
        description="[LEGACY] Hours ahead for reminders - use REMINDER_LOOKAHEAD_MINUTES instead",
    )

    # Health check settings
    HEALTH_CHECK_HOST: str = Field(
        default="0.0.0.0",
        description="Health check server host",
    )
    HEALTH_CHECK_PORT: int = Field(
        default=8080,
        gt=0,
        lt=65536,
        description="Health check server port",
    )

    # Timezone (canonical - TZ §6)
    TIMEZONE: str = Field(
        default="Europe/Moscow",
        description="Timezone for digest scheduling and user display",
    )
    # Legacy field for backward compatibility
    USER_TIMEZONE: str = Field(
        default="UTC",
        description="[LEGACY] User timezone for display purposes - use TIMEZONE instead",
    )

    # Logging settings (TZ §6)
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level",
    )
    LOG_FILE: Path | None = Field(
        default=None,
        description="Path to log file (None for stdout only)",
    )

    # News Pipeline settings (TZ §2.1)
    NEWS_LOOKBACK_HOURS: int = Field(
        default=24,
        gt=0,
        description="Hours to look back for news fetching",
    )
    NEWS_DEDUP_WINDOW_DAYS: int = Field(
        default=7,
        gt=0,
        description="Days for deduplication window",
    )
    NEWS_BATCH_MIN: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Minimum batch size for news analysis",
    )
    NEWS_BATCH_MAX: int = Field(
        default=5,
        ge=1,
        le=5,
        description="Maximum batch size for news analysis",
    )
    NEWS_DELIVERY_RETRIES: int = Field(
        default=3,
        gt=0,
        description="Max retries for digest delivery",
    )
    NEWS_DELIVERY_RETRY_DELAY_MINUTES: int = Field(
        default=5,
        gt=0,
        description="Delay between delivery retries in minutes",
    )
    FETCH_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        gt=0,
        description="Timeout for RSS fetch operations",
    )
    FETCH_MAX_RETRIES: int = Field(
        default=3,
        ge=0,
        description="Max retries for RSS fetch",
    )

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def validate_log_level(cls, v):
        """Validate LOG_LEVEL is a valid logging level."""
        if isinstance(v, str):
            v_upper = v.upper()
            valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
            if v_upper not in valid_levels:
                raise ValueError(f"LOG_LEVEL must be one of {valid_levels}, got '{v}'")
            return v_upper
        return v

    @field_validator("TIMEZONE", mode="before")
    @classmethod
    def validate_timezone(cls, v):
        """Validate TIMEZONE is a valid IANA timezone using zoneinfo."""
        if not isinstance(v, str):
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, KeyError, ValueError) as e:
            raise ValueError(f"Invalid timezone '{v}': {e}") from e
        return v

    @model_validator(mode="after")
    def validate_news_batch(self):
        """Validate NEWS_BATCH_MIN <= NEWS_BATCH_MAX <= 5."""
        if not (1 <= self.NEWS_BATCH_MIN <= self.NEWS_BATCH_MAX <= 5):
            raise ValueError(
                f"NEWS_BATCH_MIN ({self.NEWS_BATCH_MIN}) must be <= "
                f"NEWS_BATCH_MAX ({self.NEWS_BATCH_MAX}) and both must be <= 5"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def telegram_allowed_user_ids(self) -> list[int]:
        """Parse TELEGRAM_ALLOWED_USERIDS from JSON string if needed."""
        return self.TELEGRAM_ALLOWED_USER_IDS


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings instance."""
    return Settings()

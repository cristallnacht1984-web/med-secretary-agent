"""Configuration module for MedNews Secretary Agent."""
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Telegram settings
    TELEGRAM_BOT_TOKEN: SecretStr = Field(
        ..., description="Telegram bot token"
    )
    TELEGRAM_ALLOWED_USER_IDS: list[int] = Field(
        default_factory=list,
        description="List of allowed Telegram user IDs (JSON array)",
    )
    TELEGRAM_ADMIN_ID: int | None = Field(
        default=None, description="Admin Telegram user ID for critical notifications"
    )

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

    # Database settings
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./mednews.db",
        description="Async database URL",
    )

    # Google Calendar settings
    GOOGLE_CREDENTIALS_JSON: str | None = Field(
        default=None,
        description="Google OAuth credentials JSON string",
    )
    GOOGLE_CALENDAR_ID: str = Field(
        default="primary",
        description="Google Calendar ID to use",
    )

    # Scheduler settings
    DIGEST_TIME_HOUR: int = Field(
        default=6,
        ge=0,
        le=23,
        description="Hour for daily digest (UTC)",
    )
    REMINDER_POLL_INTERVAL_MINUTES: int = Field(
        default=30,
        gt=0,
        description="Interval in minutes for reminder polling",
    )
    REMINDER_WINDOW_HOURS: int = Field(
        default=2,
        gt=0,
        description="Hours ahead to check for reminders",
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

    # Timezone (for user display only, internal is always UTC)
    USER_TIMEZONE: str = Field(
        default="UTC",
        description="User timezone for display purposes",
    )

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

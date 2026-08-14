"""Configuration module for MedNews Secretary Agent."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.
    
    Attributes:
        TELEGRAM_BOT_TOKEN: Telegram bot authentication token.
        LLM_BASE_URL: Base URL for OpenAI-compatible API endpoint.
        LLM_API_KEY: API key for LLM service.
        LLM_MODEL_NAME: Name of the model to use.
        DATABASE_URL: SQLite database connection string.
        GOOGLE_CREDENTIALS_PATH: Path to Google OAuth credentials file.
        TIMEZONE: User timezone for scheduling.

    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    TELEGRAM_BOT_TOKEN: str | None = None

    # LLM (OpenAI-compatible local API)
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str = "local-key"
    LLM_MODEL_NAME: str = "qwen3.6"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///med_secretary.db"

    # Google Calendar
    GOOGLE_CREDENTIALS_PATH: str | None = None

    # Scheduler
    TIMEZONE: str = "Europe/Moscow"

    # Health check server
    HEALTH_HOST: str = "0.0.0.0"
    HEALTH_PORT: int = 8080

    def validate_required_fields(self) -> list[str]:
        """Validate that all required fields are present and non-empty.
        
        Returns:
            List of missing or empty field names.

        """
        errors = []
        required = ["TELEGRAM_BOT_TOKEN", "LLM_BASE_URL"]
        for field in required:
            value = getattr(self, field, None)
            if not value:
                errors.append(field)
        return errors

    @property
    def is_valid(self) -> bool:
        """Check if settings has all required fields.
        
        Returns:
            True if all required fields are present and non-empty.

        """
        return len(self.validate_required_fields()) == 0


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings instance.
    
    Returns:
        Settings object with validated configuration.

    """
    return Settings()

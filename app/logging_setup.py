"""Logging setup for MedNews Secretary Agent.

Uses structlog for structured logging with configurable log levels.
"""

import logging
import sys
from pathlib import Path

import structlog

try:
    from app.config import get_settings

    _settings_available = True
except ImportError:
    _settings_available = False


def setup_logging(log_level: str = "INFO", log_file: Path | None = None) -> None:
    """Configure structlog for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Optional path to log file for file handler.
    """
    if not _settings_available:
        # Fallback mode - hardcoded defaults
        log_level = "INFO"
        log_file = None

    # Parse log level
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure logging handlers
    handlers: list[logging.Handler] = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    handlers.append(console_handler)

    # File handler (if specified)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        handlers.append(file_handler)

    # Configure logging module
    logging.basicConfig(
        format="%(message)s",
        level=level,
        handlers=handlers,
    )

    # Configure structlog
    console_renderer = structlog.dev.ConsoleRenderer()
    json_renderer = structlog.processors.JSONRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            console_renderer if log_file is None else json_renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name (usually __name__).

    Returns:
        Configured structlog logger.
    """
    return structlog.get_logger(name)


# Initialize logging on module import
if _settings_available:
    try:
        settings = get_settings()
        setup_logging(settings.LOG_LEVEL, settings.LOG_FILE)
    except Exception:
        # If settings fail, use fallback
        setup_logging()
else:
    setup_logging()

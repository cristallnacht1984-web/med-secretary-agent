"""Logging setup module for MedNews Secretary Agent.

This module provides structured logging configuration using structlog with:
- JSON output for production
- Console rendering for debug mode
- Request ID tracking via contextvars
- Secret masking for sensitive data
- File rotation support
- Integration with stdlib logging
"""

import logging
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog
from structlog.types import Processor

# Sentinel object for unset parameters
_UNSET: object = object()

# Constants for log rotation
MAX_LOG_BYTES: int = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT: int = 5

# Sensitive key substrings for masking
SENSITIVE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "api_key",
    "token",
    "password",
    "secret",
    "authorization",
    "credentials",
)


def _mask_secrets_recursive(value: Any) -> Any:
    """Recursively mask sensitive values in a dictionary or list.

    Args:
        value: The value to process. Can be dict, list, tuple, or primitive.

    Returns:
        The processed value with sensitive fields masked as "***".
    """
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, val in value.items():
            key_lower = key.lower()
            if any(substring in key_lower for substring in SENSITIVE_KEY_SUBSTRINGS):
                result[key] = "***"
            else:
                result[key] = _mask_secrets_recursive(val)
        return result
    elif isinstance(value, (list, tuple)):
        return type(value)(_mask_secrets_recursive(item) for item in value)
    else:
        return value


def _mask_secrets_processor(
    logger: logging.Logger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Processor that masks sensitive values in the event dictionary.

    Args:
        logger: The logger instance.
        method_name: The logging method name (info, warning, error, etc.).
        event_dict: The event dictionary containing log data.

    Returns:
        The event dictionary with sensitive values masked.
    """
    return _mask_secrets_recursive(event_dict)


def _ensure_request_id(
    logger: logging.Logger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Ensure request_id is present in the event dictionary.

    Args:
        logger: The logger instance.
        method_name: The logging method name.
        event_dict: The event dictionary containing log data.

    Returns:
        The event dictionary with request_id set to "n/a" if not present.
    """
    if "request_id" not in event_dict:
        event_dict["request_id"] = "n/a"
    return event_dict


def _get_shared_processors() -> list[Processor]:
    """Get the shared processor pipeline for structlog and stdlib foreign_pre_chain.

    Returns:
        List of processors to be applied to all log events.
        Note: wrap_for_formatter is NOT included here - it's only for structlog config.
    """
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _mask_secrets_processor,
        _ensure_request_id,
        structlog.processors.format_exc_info,
    ]


def _remove_managed_handlers(root_logger: logging.Logger) -> None:
    """Remove previously installed managed handlers from root logger.

    Args:
        root_logger: The root logger to clean up.
    """
    handlers_to_remove = []
    for handler in root_logger.handlers:
        if getattr(handler, "_mednews_managed", False):
            handlers_to_remove.append(handler)

    for handler in handlers_to_remove:
        handler.close()
        root_logger.removeHandler(handler)


def setup_logging(
    level: str | None = None,
    log_file: Path | None | object = _UNSET,
    *,
    debug: bool | None = None,
) -> None:
    """Configure structured logging for the application.

    This function sets up structlog with JSON output for production or
    console rendering for debug mode. It configures both structlog and
    stdlib logging to use the same processing pipeline.

    Args:
        level: Log level string (e.g., "INFO", "DEBUG"). If None, uses
            Settings.LOG_LEVEL.
        log_file: Path to log file for file-based logging. If _UNSET,
            uses Settings.LOG_FILE. If explicitly None or empty, no file
            handler is created.
        debug: If True, use human-readable console output. If None, uses
            Settings.DEBUG. Explicit values override settings.

    Note:
        This function is idempotent - calling it multiple times will not
        duplicate handlers.
    """
    # Resolve configuration with precedence: explicit args > Settings > defaults
    # Try to import settings, fall back to defaults if not available
    try:
        from app.config import get_settings as _get_settings
        settings = _get_settings()
    except (ImportError, AttributeError):
        # Fallback to default values if config module is not available
        settings = None

    if level is None:
        if settings is not None:
            level = getattr(settings, "LOG_LEVEL", "INFO")
        else:
            level = "INFO"

    if log_file is _UNSET:
        if settings is not None:
            log_file_value = getattr(settings, "LOG_FILE", "")
        else:
            log_file_value = ""
        if log_file_value is None or log_file_value == "":
            log_file = None
        else:
            log_file = Path(log_file_value)

    if debug is None:
        if settings is not None:
            debug = getattr(settings, "DEBUG", False)
        else:
            debug = False

    # Get root logger and remove previous managed handlers
    root_logger = logging.getLogger()
    _remove_managed_handlers(root_logger)

    # Set log level
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Build shared processors
    shared_processors = _get_shared_processors()

    # Determine final renderer based on debug mode
    if debug:
        final_processor: Processor = structlog.dev.ConsoleRenderer(colors=False)
    else:
        final_processor = structlog.processors.JSONRenderer()

    # Configure ProcessorFormatter for stdlib integration
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=final_processor,
        foreign_pre_chain=shared_processors,
    )

    # Create stdout handler
    stream_handler = logging.StreamHandler()
    stream_handler._mednews_managed = True  # type: ignore[attr-defined]
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    # Create file handler if log_file is specified
    if log_file is not None and isinstance(log_file, Path):
        # Ensure parent directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=MAX_LOG_BYTES,
            backupCount=LOG_BACKUP_COUNT,
        )
        file_handler._mednews_managed = True  # type: ignore[attr-defined]
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Configure structlog with wrap_for_formatter as the final processor
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> Any:
    """Get a structlog logger instance.

    Args:
        name: Optional logger name. If provided, creates a named logger.
            If None, returns the default structlog logger.

    Returns:
        A structlog-bound logger that supports .info(), .warning(), .error()
        and structured keyword arguments.

    Example:
        >>> logger = get_logger("my.module")
        >>> logger.info("Event occurred", extra_data={"key": "value"})
    """
    if name is not None:
        return structlog.get_logger(name)
    return structlog.get_logger()


def new_request_id() -> str:
    """Generate and bind a new request ID to the current context.

    Creates a UUID v4 hex string (32 characters) and binds it to the
    structlog contextvars so all subsequent logs in this context will
    include this request_id.

    Returns:
        The generated request ID as a 32-character hex string.

    Example:
        >>> request_id = new_request_id()
        >>> logger.info("Processing request")  # Will include request_id
    """
    request_id = uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(request_id=request_id)
    return request_id

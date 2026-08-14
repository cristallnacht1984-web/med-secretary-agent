"""Logging setup for MedNews Secretary Agent."""
import logging
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog
from structlog.types import Processor

# Request ID context variable
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    """Generate and bind a new request ID to the current context."""
    import uuid

    rid = str(uuid.uuid4())
    _request_id.set(rid)
    return rid


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


def _mask_sensitive(value: str) -> str:
    """Mask sensitive substrings in a string value."""
    sensitive_patterns = [
        "api_key",
        "token",
        "password",
        "secret",
        "authorization",
        "credentials",
    ]
    lower_value = value.lower()
    for pattern in sensitive_patterns:
        if pattern in lower_value:
            return "***MASKED***"
    return value


def mask_secrets(
    logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Mask sensitive data in log event dict."""
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            masked = _mask_sensitive(value)
            if masked != value:
                event_dict[key] = masked
    return event_dict


def add_request_id(
    logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Add request_id from context to log event."""
    rid = _request_id.get()
    if rid is not None:
        event_dict["request_id"] = rid
    return event_dict


def setup_logging() -> None:
    """Configure structlog with JSON output and rotating file handler."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "mednews.log"

    # Create rotating file handler (5MB, 5 backups)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)

    # Console handler for development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Shared processors (no wrap_for_formatter here)
    shared_processors: list[Processor] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_request_id,
        mask_secrets,
        structlog.processors.dict_tracebacks,
    ]

    # Final processor chain for structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Formatter for file handler
    file_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    file_handler.setFormatter(file_formatter)

    # Formatter for console handler
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(),
        foreign_pre_chain=shared_processors,
    )
    console_handler.setFormatter(console_formatter)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Suppress noisy loggers
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

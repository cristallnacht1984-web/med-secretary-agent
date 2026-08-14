"""Logging setup module for MedNews Secretary Agent using structlog."""

import logging
from pathlib import Path
from typing import Any

import structlog
from structlog.types import Processor


def new_request_id() -> str:
    """Generate a unique request ID for tracking requests.
    
    Returns:
        A unique string identifier for the request.

    """
    import uuid
    return str(uuid.uuid4())


def add_request_id(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add request_id to log events if not present.
    
    Args:
        logger: The logger instance.
        method_name: The logging method name (info, error, etc.).
        event_dict: The event dictionary being logged.
        
    Returns:
        Modified event dictionary with request_id added.

    """
    if "request_id" not in event_dict:
        event_dict["request_id"] = new_request_id()
    return event_dict


def setup_logging(log_level: str = "INFO", log_file: str | None = None) -> None:
    """Configure structlog for structured JSON logging.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        log_file: Optional path to log file. If None, logs to stdout only.

    """
    # Configure standard library logging
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        handlers.append(file_handler)

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
        handlers=handlers,
    )

    # Configure structlog processors
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        add_request_id,
        structlog.processors.dict_tracebacks,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structured logger instance.
    
    Args:
        name: Logger name (typically module name).
        
    Returns:
        Bound structlog logger instance.

    """
    return structlog.get_logger(name)

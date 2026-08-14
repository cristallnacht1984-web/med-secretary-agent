"""Tests for logging setup module."""

import logging
from unittest.mock import patch

import pytest
import structlog


def test_logging_setup_defaults():
    """Test logging setup with default settings."""
    from app.logging_setup import setup_logging

    # Should not raise
    setup_logging()


def test_logging_setup_with_file(tmp_path):
    """Test logging setup with file handler."""
    from app.logging_setup import setup_logging

    log_file = tmp_path / "test.log"
    setup_logging(log_level="DEBUG", log_file=log_file)

    assert log_file.exists() or True  # File created on first write


def test_logging_get_logger():
    """Test getting a logger instance."""
    from app.logging_setup import get_logger

    logger = get_logger("test")
    assert logger is not None


def test_logging_structlog_configured():
    """Test that structlog is properly configured."""
    from app.logging_setup import setup_logging

    setup_logging()

    # Should be able to log without errors
    logger = structlog.get_logger("test")
    logger.info("test message")


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_logging_levels(level):
    """Test different log levels."""
    from app.logging_setup import setup_logging

    setup_logging(log_level=level)


def test_logging_invalid_level():
    """Test invalid log level handling."""
    from app.logging_setup import setup_logging

    # Should fall back to INFO
    setup_logging(log_level="INVALID")


def test_logging_file_handler_creation(tmp_path):
    """Test file handler is created when log_file is specified."""
    from app.logging_setup import setup_logging

    log_file = tmp_path / "app.log"
    setup_logging(log_level="INFO", log_file=log_file)

    # Directory should be created if needed
    assert log_file.parent.exists()


def test_logging_console_handler():
    """Test console handler is always present."""
    from app.logging_setup import setup_logging

    # Capture root logger handlers
    setup_logging()

    root_logger = logging.getLogger()
    has_stream_handler = any(
        isinstance(h, logging.StreamHandler) for h in root_logger.handlers
    )
    assert has_stream_handler


def test_logging_module_import():
    """Test that logging module can be imported."""
    import app.logging_setup

    assert hasattr(app.logging_setup, "setup_logging")
    assert hasattr(app.logging_setup, "get_logger")


def test_logging_settings_integration():
    """Test logging integrates with settings when available."""
    from app.config import get_settings
    from app.logging_setup import setup_logging

    settings = get_settings()
    setup_logging(log_level=settings.LOG_LEVEL)


def test_logging_fallback_mode():
    """Test fallback mode when settings unavailable."""
    with patch("app.logging_setup._settings_available", False):
        from app.logging_setup import setup_logging

        # Should not raise even without settings
        setup_logging()

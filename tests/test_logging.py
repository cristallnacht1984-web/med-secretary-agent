"""Tests for logging_setup module."""

import logging

from app.logging_setup import add_request_id, get_logger, new_request_id, setup_logging


class TestNewRequestId:
    """Test cases for new_request_id function."""

    def test_new_request_id_returns_string(self) -> None:
        """Test that new_request_id returns a string."""
        request_id = new_request_id()
        assert isinstance(request_id, str)

    def test_new_request_id_unique(self) -> None:
        """Test that new_request_id generates unique IDs."""
        id1 = new_request_id()
        id2 = new_request_id()
        assert id1 != id2


class TestAddRequestId:
    """Test cases for add_request_id processor."""

    def test_add_request_id_adds_to_event_dict(self) -> None:
        """Test that add_request_id adds request_id to event dict."""
        event_dict: dict[str, str] = {}
        result = add_request_id(logging.getLogger(), "info", event_dict)
        assert "request_id" in result

    def test_add_request_id_preserves_existing(self) -> None:
        """Test that add_request_id preserves existing request_id."""
        event_dict = {"request_id": "existing-id"}
        result = add_request_id(logging.getLogger(), "info", event_dict)
        assert result["request_id"] == "existing-id"


class TestSetupLogging:
    """Test cases for setup_logging function."""

    def test_setup_logging_configures_structlog(self) -> None:
        """Test that setup_logging configures structlog."""
        setup_logging(log_level="INFO")
        # If no exception, structlog is configured
        logger = get_logger("test")
        assert logger is not None

    def test_setup_logging_with_log_file(self, tmp_path) -> None:
        """Test setup_logging with log file."""
        log_file = tmp_path / "test.log"
        setup_logging(log_level="INFO", log_file=str(log_file))
        assert log_file.exists()


class TestGetLogger:
    """Test cases for get_logger function."""

    def test_get_logger_returns_bound_logger(self) -> None:
        """Test that get_logger returns a bound logger."""
        setup_logging()
        logger = get_logger("test_module")
        # Logger should be callable and have bound methods
        assert hasattr(logger, "info")
        assert hasattr(logger, "error")
        assert hasattr(logger, "warning")

    def test_get_logger_different_names(self) -> None:
        """Test that get_logger returns different loggers for different names."""
        setup_logging()
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        assert logger1 is not logger2

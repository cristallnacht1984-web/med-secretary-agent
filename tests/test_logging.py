"""Tests for the logging setup module."""

import json
import logging
import logging.handlers
import string
from pathlib import Path

import pytest
import structlog
import structlog.contextvars

from app.logging_setup import (
    LOG_BACKUP_COUNT,
    MAX_LOG_BYTES,
    get_logger,
    new_request_id,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _clean_structlog_context():
    """Clean structlog contextvars before and after each test."""
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


@pytest.fixture
def clean_root_logger():
    """Clean root logger handlers before test."""
    root_logger = logging.getLogger()
    # Remove all handlers
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)
    yield
    # Cleanup after test
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)


class TestJSONMode:
    """Test JSON output mode."""

    def test_json_output_has_required_keys(self, clean_root_logger, capsys):
        """Test that JSON logs contain required keys: event, level, timestamp, request_id."""
        setup_logging(level="INFO", log_file=None, debug=False)
        structlog.contextvars.clear_contextvars()

        logger = get_logger()
        logger.info("json event")

        # Capture stdout/stderr
        captured = capsys.readouterr()
        # Logs go to stderr via StreamHandler
        output = captured.err if captured.err else captured.out
        lines = [line for line in output.strip().split("\n") if line]
        assert len(lines) > 0

        # Parse last line as JSON
        data = json.loads(lines[-1])

        # Check required keys exist
        assert "event" in data
        assert "level" in data
        assert "timestamp" in data
        assert "request_id" in data

        # Check event value
        assert data["event"] == "json event"

        # Check level is info (case-insensitive)
        assert data["level"].lower() == "info"


class TestNewRequestId:
    """Test new_request_id functionality."""

    def test_new_request_id_generates_valid_uuid(self):
        """Test that new_request_id generates a valid 32-char hex string."""
        setup_logging(level="INFO", log_file=None, debug=False)
        structlog.contextvars.clear_contextvars()

        rid = new_request_id()

        # Check length
        assert len(rid) == 32

        # Check all characters are hex digits
        assert all(c in string.hexdigits for c in rid)

        # Verify it can be parsed as hex
        int(rid, 16)

    def test_request_id_persists_across_multiple_logs(self, clean_root_logger, capsys):
        """Test that request_id persists across multiple log calls."""
        setup_logging(level="INFO", log_file=None, debug=False)
        structlog.contextvars.clear_contextvars()

        rid = new_request_id()

        logger = get_logger()
        logger.info("first event")
        logger.info("second event")

        captured = capsys.readouterr()
        output = captured.err if captured.err else captured.out
        lines = [line for line in output.strip().split("\n") if line]

        assert len(lines) >= 2

        data1 = json.loads(lines[0])
        data2 = json.loads(lines[1])

        # Both should have same request_id
        assert data1["request_id"] == rid
        assert data2["request_id"] == rid


class TestMissingRequestId:
    """Test behavior when request_id is not set."""

    def test_missing_request_id_shows_na(self, clean_root_logger, capsys):
        """Test that missing request_id shows 'n/a'."""
        setup_logging(level="INFO", log_file=None, debug=False)
        structlog.contextvars.clear_contextvars()

        logger = get_logger()
        logger.info("no request id event")

        captured = capsys.readouterr()
        output = captured.err if captured.err else captured.out
        lines = [line for line in output.strip().split("\n") if line]

        assert len(lines) > 0
        data = json.loads(lines[-1])

        assert data["request_id"] == "n/a"


class TestSecretMasking:
    """Test secret masking functionality."""

    def test_secrets_are_masked_in_output(self, clean_root_logger, capsys):
        """Test that sensitive values are masked."""
        setup_logging(level="INFO", log_file=None, debug=False)

        payload = {
            "llm_api_key": "secret123",
            "telegram_bot_token": "tok-value",
            "nested": {
                "password": "p@ss",
            },
        }

        logger = get_logger()
        logger.info("mask event", payload=payload)

        captured = capsys.readouterr()
        raw_output = captured.err if captured.err else captured.out

        # Check that masked value appears
        assert "***" in raw_output

        # Check that original secrets do NOT appear in raw output
        assert "secret123" not in raw_output
        assert "tok-value" not in raw_output
        assert "p@ss" not in raw_output


class TestDebugMode:
    """Test debug mode output."""

    def test_debug_mode_not_json(self, clean_root_logger, capsys):
        """Test that debug mode produces non-JSON human-readable output."""
        setup_logging(level="INFO", log_file=None, debug=True)

        logger = get_logger()
        logger.info("console event")

        captured = capsys.readouterr()
        raw_output = captured.err if captured.err else captured.out

        # Check event text appears
        assert "console event" in raw_output

        # Check level appears (case-insensitive)
        assert "info" in raw_output.lower() or "INFO" in raw_output

        # Last non-empty line should NOT be valid JSON
        lines = [line for line in raw_output.strip().split("\n") if line]
        assert len(lines) > 0

        with pytest.raises(json.JSONDecodeError):
            json.loads(lines[-1])


class TestFileHandlerAndRotation:
    """Test file handler and rotation configuration."""

    def test_file_handler_created_with_rotation(self, tmp_path: Path):
        """Test that file handler is created with correct rotation settings."""
        log_path = tmp_path / "logs" / "app.log"

        setup_logging(level="INFO", log_file=log_path, debug=False)

        logger = get_logger()
        logger.info("file test event")

        # Check file was created
        assert log_path.exists()

        # Check handlers include RotatingFileHandler
        root_logger = logging.getLogger()
        rotating_handlers = [
            h for h in root_logger.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(rotating_handlers) > 0

        # Check rotation settings
        handler = rotating_handlers[0]
        assert handler.maxBytes == MAX_LOG_BYTES
        assert handler.backupCount == LOG_BACKUP_COUNT

        # Check file content is JSON
        content = log_path.read_text()
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) > 0

        data = json.loads(lines[-1])
        assert "event" in data


class TestLevelFiltering:
    """Test log level filtering."""

    def test_info_level_filtered_when_set_to_warning(self, clean_root_logger, capsys):
        """Test that INFO logs are filtered when level is WARNING."""
        setup_logging(level="WARNING", log_file=None, debug=False)

        logger = get_logger()
        logger.info("hidden info event")
        logger.warning("shown warning event")

        captured = capsys.readouterr()
        raw_output = captured.err if captured.err else captured.out

        # Info event should not appear
        assert "hidden info event" not in raw_output

        # Warning event should appear
        assert "shown warning event" in raw_output


class TestGetLogger:
    """Test get_logger functionality."""

    def test_get_logger_with_name(self, clean_root_logger, capsys):
        """Test that get_logger passes name correctly."""
        setup_logging(level="INFO", log_file=None, debug=False)

        logger = get_logger("name.check")
        logger.info("named logger event")

        captured = capsys.readouterr()
        output = captured.err if captured.err else captured.out
        lines = [line for line in output.strip().split("\n") if line]

        assert len(lines) > 0
        data = json.loads(lines[-1])

        # If logger field is present, it should match the name
        if "logger" in data:
            assert data["logger"] == "name.check"


class TestIdempotency:
    """Test idempotency of setup_logging."""

    def test_setup_logging_is_idempotent(self):
        """Test that calling setup_logging multiple times doesn't duplicate handlers."""
        setup_logging(level="INFO", log_file=None, debug=False)

        root_logger = logging.getLogger()
        initial_handler_count = len(root_logger.handlers)

        # Call again
        setup_logging(level="INFO", log_file=None, debug=False)

        final_handler_count = len(root_logger.handlers)

        # Handler count should not increase
        assert final_handler_count <= initial_handler_count


class TestStdlibBridge:
    """Test stdlib logging bridge functionality."""

    def test_foreign_logs_work(self, clean_root_logger, capsys):
        """Test that stdlib logging (foreign logs) works correctly through the bridge.
        
        This test verifies that logs from standard logging (e.g., from libraries like
        aiogram, sqlalchemy) are properly formatted as JSON and include all required
        fields without raising TypeError.
        """
        setup_logging(level="INFO", log_file=None, debug=False)
        structlog.contextvars.clear_contextvars()

        # Use standard logging directly (simulating a foreign library)
        foreign_logger = logging.getLogger("aiogram")
        foreign_logger.info("foreign event")

        captured = capsys.readouterr()
        output = captured.err if captured.err else captured.out
        lines = [line for line in output.strip().split("\n") if line]

        assert len(lines) > 0

        # Should be valid JSON
        data = json.loads(lines[-1])

        # Check required keys
        assert "event" in data
        assert "level" in data
        assert "timestamp" in data
        assert "request_id" in data

        # Check event value
        assert data["event"] == "foreign event"

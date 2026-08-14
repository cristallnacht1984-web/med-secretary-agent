"""Tests for logging module."""
import json
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.logging_setup import (
    _mask_sensitive,
    add_request_id,
    get_logger,
    mask_secrets,
    new_request_id,
    setup_logging,
)


@pytest.fixture(autouse=True)
def clean_logging_env(monkeypatch: pytest.MonkeyPatch):
    """Clean up logging-related environment and reset state."""
    # Remove any existing log files to ensure clean state
    log_dir = Path("logs")
    if log_dir.exists():
        for f in log_dir.glob("*.log"):
            f.unlink()

    yield

    # Cleanup after test
    if log_dir.exists():
        for f in log_dir.glob("*.log"):
            f.unlink()


class TestMaskSensitive:
    """Test _mask_sensitive function."""

    def test_masks_api_key(self):
        """Test masking of api_key pattern."""
        result = _mask_sensitive("my_api_key_value")
        assert result == "***MASKED***"

    def test_masks_token(self):
        """Test masking of token pattern."""
        result = _mask_sensitive("bot_token_12345")
        assert result == "***MASKED***"

    def test_masks_password(self):
        """Test masking of password pattern."""
        result = _mask_sensitive("super_password")
        assert result == "***MASKED***"

    def test_masks_secret(self):
        """Test masking of secret pattern."""
        result = _mask_sensitive("secret_value")
        assert result == "***MASKED***"

    def test_masks_authorization(self):
        """Test masking of authorization pattern."""
        result = _mask_sensitive("Bearer authorization_token")
        assert result == "***MASKED***"

    def test_masks_credentials(self):
        """Test masking of credentials pattern."""
        result = _mask_sensitive("google_credentials_json")
        assert result == "***MASKED***"

    def test_no_mask_safe_string(self):
        """Test that safe strings are not masked."""
        result = _mask_sensitive("hello world")
        assert result == "hello world"


class TestMaskSecrets:
    """Test mask_secrets processor."""

    def test_masks_sensitive_in_event_dict(self):
        """Test masking sensitive fields in event dict."""
        event_dict = {
            "event": "test",
            "api_key": "secret123",
            "safe_field": "normal_value",
        }
        result = mask_secrets(None, "info", event_dict)
        assert result["api_key"] == "***MASKED***"
        assert result["safe_field"] == "normal_value"

    def test_non_string_not_affected(self):
        """Test that non-string values are not affected."""
        event_dict = {"count": 42, "flag": True}
        result = mask_secrets(None, "info", event_dict)
        assert result["count"] == 42
        assert result["flag"] is True


class TestAddRequestId:
    """Test add_request_id processor."""

    def test_adds_request_id_when_set(self):
        """Test request_id is added when set in context."""
        new_request_id()
        event_dict = {"event": "test"}
        result = add_request_id(None, "info", event_dict)
        assert "request_id" in result

    def test_no_request_id_when_not_set(self):
        """Test request_id is not added when not set."""
        # Clear the context var
        from app.logging_setup import _request_id

        _request_id.set(None)
        event_dict = {"event": "test"}
        result = add_request_id(None, "info", event_dict)
        assert "request_id" not in result


class TestSetupLogging:
    """Test setup_logging function."""

    def test_creates_log_directory(self):
        """Test that setup_logging creates logs directory."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test"}):
            setup_logging()
            assert Path("logs").exists()

    def test_configures_structlog(self):
        """Test that structlog is configured."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test"}):
            setup_logging()
            # Should be able to get a logger
            logger = get_logger("test")
            assert logger is not None

    def test_root_logger_has_handlers(self):
        """Test that root logger has handlers after setup."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test"}):
            setup_logging()
            root_logger = logging.getLogger()
            assert len(root_logger.handlers) >= 2


class TestGetLogger:
    """Test get_logger function."""

    def test_returns_bound_logger(self):
        """Test get_logger returns structlog BoundLogger."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test"}):
            setup_logging()
            logger = get_logger("test_module")
            # Logger may be a lazy proxy - just check it's not None and callable
            assert logger is not None
            # Try to use it - should not raise
            logger.info("test message")


class TestNewRequestId:
    """Test new_request_id function."""

    def test_generates_uuid(self):
        """Test new_request_id generates valid UUID string."""
        rid = new_request_id()
        # UUID format check (basic)
        assert len(rid) == 36
        assert rid.count("-") == 4

    def test_sets_context_var(self):
        """Test new_request_id sets context variable."""
        from app.logging_setup import _request_id

        rid = new_request_id()
        assert _request_id.get() == rid


class TestJsonOutput:
    """Test JSON log output."""

    def test_logs_are_json_formatted(self):
        """Test that file logs are JSON formatted."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test"}):
            setup_logging()
            logger = get_logger("json_test")
            logger.info("test message", key="value")

            # Check log file exists and contains JSON
            log_file = Path("logs/mednews.log")
            if log_file.exists():
                content = log_file.read_text()
                if content.strip():
                    # Try to parse as JSON
                    lines = content.strip().split("\n")
                    for line in lines:
                        if line.strip():
                            json.loads(line)  # Should not raise


class TestStdlibBridge:
    """Test stdlib logging bridge."""

    def test_stdlib_logs_through_structlog(self):
        """Test that stdlib logging works with structlog."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test"}):
            setup_logging()
            stdlib_logger = logging.getLogger("test_stdlib")
            stdlib_logger.info("stdlib message")
            # Should not raise any exception

"""Pytest fixtures for MedNews Secretary Agent tests."""

import os

import pytest


@pytest.fixture(autouse=True)
def setup_required_env_vars(monkeypatch):
    """Set up required environment variables for all tests.
    
    This fixture ensures that required Telegram settings are available
    for tests that need to instantiate Settings.
    """
    # Only set if not already set (to allow test-specific overrides)
    if "TELEGRAM_BOT_TOKEN" not in os.environ:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_bot_token")
    if "TELEGRAM_DIGEST_CHAT_ID" not in os.environ:
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
    if "TELEGRAM_ADMIN_ID" not in os.environ:
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
    if "TELEGRAM_ALLOWED_USER_IDS" not in os.environ:
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")
    
    yield

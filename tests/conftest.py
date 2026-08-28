"""Pytest fixtures for MedNews Secretary Agent tests."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch):
    """Clean environment and clear Settings cache before each test.
    
    This fixture ensures that:
    1. Physical .env file is removed (to prevent pydantic-settings auto-loading)
    2. Environment variables are cleared to prevent leakage between tests
    3. Settings cache is cleared to force re-reading of environment
    """
    from app.config import get_settings
    
    # Phase 0: Remove physical .env file that would interfere with tests
    env_file_path = Path(__file__).parent.parent / ".env"
    env_backup = None
    if env_file_path.exists():
        env_backup = env_file_path.read_text(encoding="utf-8")
        env_file_path.unlink()
    
    # Phase 1: Clear ALL environment variables that could affect Settings
    # Get all env vars that start with known prefixes or match exactly
    env_var_prefixes = ["TELEGRAM_", "LLM_", "LOG_", "DIGEST_", "REMINDER_", 
                        "HEALTH_", "USER_", "TIMEZONE", "DATABASE_", "GOOGLE_", 
                        "NEWS_", "FETCH_"]
    vars_to_clear = []
    for key in os.environ.keys():
        if any(key.startswith(prefix) for prefix in env_var_prefixes):
            vars_to_clear.append(key)
    
    for var_name in vars_to_clear:
        monkeypatch.delenv(var_name, raising=False)
    
    # Phase 2: Clear Settings cache
    get_settings.cache_clear()
    
    yield
    
    # Restore .env file if it was backed up
    if env_backup is not None:
        env_file_path.write_text(env_backup, encoding="utf-8")


@pytest.fixture(autouse=True)
def setup_required_env_vars(monkeypatch, request):
    """Set up required environment variables for all tests.
    
    This fixture ensures that required Telegram settings are available
    for tests that need to instantiate Settings.
    
    If a test is marked with @pytest.mark.no_token, TELEGRAM_BOT_TOKEN
    will NOT be set, allowing tests to verify token validation.
    """
    # Check if test is marked to run without token
    mark_no_token = request.node.get_closest_marker("no_token")
    
    # Also check by test name for test_telegram_bot_token_required
    test_name = request.node.name
    is_token_test = "test_telegram_bot_token_required" in test_name
    
    # Only set if not already set (to allow test-specific overrides)
    # Skip setting TELEGRAM_BOT_TOKEN if test is marked with no_token
    # or if it's the token validation test
    if (mark_no_token is None and not is_token_test) and "TELEGRAM_BOT_TOKEN" not in os.environ:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_bot_token")
    if "TELEGRAM_DIGEST_CHAT_ID" not in os.environ:
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
    if "TELEGRAM_ADMIN_ID" not in os.environ:
        monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
    # TELEGRAM_ALLOWED_USER_IDS is NOT set here - it has a default in Settings
    # and some tests verify the empty default behavior
    
    yield

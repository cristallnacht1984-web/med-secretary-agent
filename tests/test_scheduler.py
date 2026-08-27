"""Tests for app/scheduler.py module.

Covers build_scheduler, run_digest_job, and run_reminder_job with comprehensive mocking.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import STATE_STOPPED
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings, get_settings
from app.scheduler import build_scheduler, run_digest_job, run_reminder_job


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clean environment and clear settings cache before each test."""
    # Remove all Settings-related env vars
    env_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_DIGEST_CHAT_ID",
        "DIGEST_HOUR",
        "DIGEST_MINUTE",
        "TIMEZONE",
        "REMINDER_POLL_INTERVAL_MINUTES",
        "NEWS_LOOKBACK_HOURS",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
        "DATABASE_URL",
        "GOOGLE_CREDENTIALS_FILE",
        "GOOGLE_TOKEN_FILE",
        "GOOGLE_CALENDAR_ID",
        "LOG_LEVEL",
        "LOG_FILE",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()


@pytest.fixture
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Create mock settings for tests."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[123]")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "456")
    monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-100789")
    monkeypatch.setenv("DIGEST_HOUR", "6")
    monkeypatch.setenv("DIGEST_MINUTE", "0")
    monkeypatch.setenv("TIMEZONE", "Europe/Moscow")
    monkeypatch.setenv("REMINDER_POLL_INTERVAL_MINUTES", "30")
    monkeypatch.setenv("NEWS_LOOKBACK_HOURS", "24")
    monkeypatch.setenv("LLM_BASE_URL", "http://test/v1")
    monkeypatch.setenv("LLM_API_KEY", "test_key")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "/tmp/creds.json")
    return get_settings()


class TestBuildScheduler:
    """Tests for build_scheduler function."""

    def test_returns_asyncioscheduler(self, mock_settings: Settings) -> None:
        """build_scheduler returns AsyncIOScheduler instance."""
        scheduler = build_scheduler(mock_settings)
        assert isinstance(scheduler, AsyncIOScheduler)

    def test_has_exactly_two_jobs(self, mock_settings: Settings) -> None:
        """Scheduler has exactly 2 jobs with correct ids."""
        scheduler = build_scheduler(mock_settings)
        jobs = scheduler.get_jobs()
        assert len(jobs) == 2
        job_ids = {job.id for job in jobs}
        assert job_ids == {"digest", "reminder"}

    def test_digest_trigger_is_crontrigger(self, mock_settings: Settings) -> None:
        """Digest job uses CronTrigger with correct parameters."""
        scheduler = build_scheduler(mock_settings)
        digest_job = scheduler.get_job("digest")
        assert digest_job is not None
        trigger = digest_job.trigger
        assert isinstance(trigger, CronTrigger)
        # Access hour/minute via fields
        hour_field = [f for f in trigger.fields if f.name == "hour"][0]
        minute_field = [f for f in trigger.fields if f.name == "minute"][0]
        assert "6" in str(hour_field.expressions[0])
        assert "0" in str(minute_field.expressions[0])
        assert str(trigger.timezone) == "Europe/Moscow"

    def test_reminder_trigger_is_intervaltrigger(self, mock_settings: Settings) -> None:
        """Reminder job uses IntervalTrigger with correct interval."""
        scheduler = build_scheduler(mock_settings)
        reminder_job = scheduler.get_job("reminder")
        assert reminder_job is not None
        trigger = reminder_job.trigger
        assert isinstance(trigger, IntervalTrigger)
        # interval.total_seconds() / 60 == minutes
        assert trigger.interval.total_seconds() == 30 * 60

    def test_jobs_have_max_instances_one(self, mock_settings: Settings) -> None:
        """Both jobs have max_instances=1."""
        scheduler = build_scheduler(mock_settings)
        for job_id in ["digest", "reminder"]:
            job = scheduler.get_job(job_id)
            assert job is not None
            assert job.max_instances == 1

    def test_jobs_have_coalesce_true(self, mock_settings: Settings) -> None:
        """Both jobs have coalesce=True."""
        scheduler = build_scheduler(mock_settings)
        for job_id in ["digest", "reminder"]:
            job = scheduler.get_job(job_id)
            assert job is not None
            assert job.coalesce is True

    def test_build_scheduler_with_none_settings(
        self, mock_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build_scheduler(None) uses get_settings()."""
        # mock_settings already set up env
        scheduler = build_scheduler(None)
        assert isinstance(scheduler, AsyncIOScheduler)
        jobs = scheduler.get_jobs()
        assert len(jobs) == 2

    def test_digest_hour_change_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Changing DIGEST_HOUR via env changes trigger hour."""
        get_settings.cache_clear()
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[123]")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-100789")
        monkeypatch.setenv("DIGEST_HOUR", "8")
        monkeypatch.setenv("DIGEST_MINUTE", "30")
        monkeypatch.setenv("TIMEZONE", "UTC")
        monkeypatch.setenv("REMINDER_POLL_INTERVAL_MINUTES", "30")
        monkeypatch.setenv("LLM_BASE_URL", "http://test/v1")
        monkeypatch.setenv("LLM_API_KEY", "test_key")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "/tmp/creds.json")

        settings = get_settings()
        scheduler = build_scheduler(settings)
        digest_job = scheduler.get_job("digest")
        assert digest_job is not None
        trigger = digest_job.trigger
        assert isinstance(trigger, CronTrigger)
        # Access hour/minute via fields
        hour_field = [f for f in trigger.fields if f.name == "hour"][0]
        minute_field = [f for f in trigger.fields if f.name == "minute"][0]
        assert "8" in str(hour_field.expressions[0])
        assert "30" in str(minute_field.expressions[0])


class TestRunDigestJob:
    """Tests for run_digest_job async function."""

    @pytest.mark.asyncio
    async def test_nonempty_digest_calls_send(
        self, mock_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-empty digest triggers send_digest_to_telegram."""
        with patch("app.scheduler.build_digest_message", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = "Test digest content"
            with patch("app.scheduler.send_digest_to_telegram", new_callable=AsyncMock) as mock_send:
                get_settings.cache_clear()
                await run_digest_job()

            mock_build.assert_called_once()
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_digest_no_send(
        self, mock_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty digest does NOT call send_digest_to_telegram."""
        with patch("app.scheduler.build_digest_message", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = ""
            with patch("app.scheduler.send_digest_to_telegram", new_callable=AsyncMock) as mock_send:
                await run_digest_job()

            mock_build.assert_called_once()
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_logs_and_notifies_admin(
        self, mock_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exception in digest job logs error and notifies admin."""
        with patch("app.scheduler.build_digest_message", new_callable=AsyncMock) as mock_build:
            mock_build.side_effect = RuntimeError("Test error")
            with patch("aiogram.Bot") as mock_bot_class:
                mock_bot = MagicMock()
                mock_bot.send_message = AsyncMock()
                mock_bot.close = AsyncMock()
                mock_bot_class.return_value = mock_bot

                # Should not raise
                await run_digest_job()

                mock_bot.send_message.assert_called_once()
                # Verify admin notification
                call_args = mock_bot.send_message.call_args
                assert call_args[1]["chat_id"] == 456  # TELEGRAM_ADMIN_ID

    @pytest.mark.asyncio
    async def test_request_id_bound(
        self, mock_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_digest_job binds request_id via new_request_id/bind_contextvars."""
        with patch("app.scheduler.new_request_id") as mock_new_req:
            mock_new_req.return_value = "test-request-id-123"
            with patch("app.scheduler.bind_contextvars") as mock_bind:
                with patch("app.scheduler.build_digest_message", new_callable=AsyncMock) as mock_build:
                    mock_build.return_value = "test"
                    await run_digest_job()

                mock_new_req.assert_called_once()
                mock_bind.assert_called_once_with(request_id="test-request-id-123")


class TestRunReminderJob:
    """Tests for run_reminder_job async function."""

    @pytest.mark.asyncio
    async def test_poll_and_remind_called(
        self, mock_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_reminder_job calls ReminderEngine.poll_and_remind()."""
        with patch("app.scheduler.ReminderEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.poll_and_remind = AsyncMock(return_value=2)
            mock_engine_class.return_value = mock_engine

            await run_reminder_job()

            mock_engine.poll_and_remind.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_logged_not_propagated(
        self, mock_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exception in reminder job is logged, not propagated."""
        with patch("app.scheduler.ReminderEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.poll_and_remind = AsyncMock(side_effect=RuntimeError("Test error"))
            mock_engine_class.return_value = mock_engine

            # Should not raise
            result = await run_reminder_job()
            assert result is None  # Function returns None

    @pytest.mark.asyncio
    async def test_request_id_bound(
        self, mock_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_reminder_job binds request_id."""
        with patch("app.scheduler.new_request_id") as mock_new_req:
            mock_new_req.return_value = "reminder-req-id"
            with patch("app.scheduler.bind_contextvars") as mock_bind:
                with patch("app.scheduler.ReminderEngine") as mock_engine_class:
                    mock_engine = MagicMock()
                    mock_engine.poll_and_remind = AsyncMock(return_value=0)
                    mock_engine_class.return_value = mock_engine

                    await run_reminder_job()

                mock_new_req.assert_called_once()
                mock_bind.assert_called_once_with(request_id="reminder-req-id")


class TestSchedulerShutdown:
    """Tests for graceful shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_wait_true(self, mock_settings: Settings) -> None:
        """scheduler.shutdown(wait=True) works correctly."""
        scheduler = build_scheduler(mock_settings)
        # Start scheduler (requires running event loop)
        scheduler.start()
        await asyncio.sleep(0.01)  # Let it start
        # Shutdown with wait=True
        scheduler.shutdown(wait=True)
        await asyncio.sleep(0)  # Give event loop time to process shutdown
        # Scheduler should be stopped
        assert scheduler.state == STATE_STOPPED

    @pytest.mark.asyncio
    async def test_async_shutdown(self, mock_settings: Settings) -> None:
        """Async shutdown pattern works."""
        scheduler = build_scheduler(mock_settings)
        scheduler.start()
        await asyncio.sleep(0.01)  # Let it start
        scheduler.shutdown(wait=True)
        await asyncio.sleep(0)  # Give event loop time to process shutdown
        assert scheduler.state == STATE_STOPPED

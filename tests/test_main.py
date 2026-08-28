"""Tests for main.py entry point."""
import asyncio
import inspect
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_settings():
    """Mock settings."""
    settings = MagicMock()
    settings.TELEGRAM_BOT_TOKEN.get_secret_value.return_value = "dummy-token"
    settings.HEALTH_CHECK_HOST = "127.0.0.1"
    settings.HEALTH_CHECK_PORT = 8080
    settings.TIMEZONE = "UTC"
    return settings


@pytest.fixture
def mock_all(mock_settings):
    """Mock all main dependencies."""
    mocks = {}

    with (
        patch("main.get_settings", return_value=mock_settings) as mocks["get_settings"],
        patch("main.setup_logging") as mocks["setup_logging"],
        patch("main.get_logger") as mocks["get_logger"],
        patch("main.new_request_id", return_value="req-123") as mocks["new_request_id"],
        patch("main.bind_contextvars") as mocks["bind_contextvars"],
        patch("main.create_app", new_callable=AsyncMock) as mocks["create_app"],
        patch("main.web.AppRunner") as mocks["AppRunner"],
        patch("main.web.TCPSite") as mocks["TCPSite"],
        patch("main.init_db", new_callable=AsyncMock) as mocks["init_db"],
        patch("main.Bot") as mocks["Bot"],
        patch("main.Dispatcher") as mocks["Dispatcher"],
        patch("main.MemoryStorage") as mocks["MemoryStorage"],
        patch("main.build_router") as mocks["build_router"],
        patch("main.build_scheduler") as mocks["build_scheduler"],
        patch("main.close_db", new_callable=AsyncMock) as mocks["close_db"],
    ):
        mock_logger = MagicMock()
        mocks["get_logger"].return_value = mock_logger
        mocks["logger"] = mock_logger

        mock_runner = MagicMock()
        mock_runner.setup = AsyncMock()
        mock_runner.cleanup = AsyncMock()
        mocks["AppRunner"].return_value = mock_runner
        mocks["runner"] = mock_runner

        mock_site = MagicMock()
        mock_site.start = AsyncMock()
        mocks["TCPSite"].return_value = mock_site

        mock_bot = MagicMock()
        mock_bot.session.close = AsyncMock()
        mocks["Bot"].return_value = mock_bot
        mocks["bot"] = mock_bot

        mock_dp = MagicMock()
        mock_dp.start_polling = AsyncMock()
        mocks["Dispatcher"].return_value = mock_dp
        mocks["dp"] = mock_dp

        mock_router = MagicMock()
        mocks["build_router"].return_value = mock_router

        mock_sched = MagicMock()
        mock_sched.start = MagicMock()
        mock_sched.shutdown = AsyncMock()
        mocks["build_scheduler"].return_value = mock_sched
        mocks["scheduler"] = mock_sched

        yield mocks


@pytest.mark.asyncio
async def test_startup_order_logging_and_db(mock_all):
    """setup_logging before init_db."""
    from main import main

    call_order = []
    mock_all["setup_logging"].side_effect = lambda: call_order.append("log")
    mock_all["init_db"].side_effect = lambda: call_order.append("db")
    mock_all["dp"].start_polling = AsyncMock()

    await main()
    assert call_order.index("log") < call_order.index("db")


@pytest.mark.asyncio
async def test_init_db_before_polling(mock_all):
    """init_db before start_polling."""
    from main import main

    call_order = []
    mock_all["init_db"].side_effect = lambda: call_order.append("db")
    mock_all["dp"].start_polling.side_effect = lambda *a, **k: call_order.append("poll")

    await main()
    assert call_order.index("db") < call_order.index("poll")


@pytest.mark.asyncio
async def test_health_starts_before_polling(mock_all):
    """Health server setup before polling."""
    from main import main

    call_order = []
    mock_all["runner"].setup.side_effect = lambda: call_order.append("health")
    mock_all["dp"].start_polling.side_effect = lambda *a, **k: call_order.append("poll")

    await main()
    assert call_order.index("health") < call_order.index("poll")


@pytest.mark.asyncio
async def test_scheduler_built_and_started(mock_all):
    """build_scheduler called and start() invoked."""
    from main import main

    mock_all["dp"].start_polling = AsyncMock()
    await main()

    mock_all["build_scheduler"].assert_called_once()
    mock_all["scheduler"].start.assert_called_once()


@pytest.mark.asyncio
async def test_router_included_in_dispatcher(mock_all):
    """build_router result passed to include_router."""
    from main import main

    mock_all["dp"].start_polling = AsyncMock()
    await main()

    mock_all["build_router"].assert_called_once()
    mock_all["dp"].include_router.assert_called_once_with(mock_all["build_router"].return_value)


@pytest.mark.asyncio
async def test_start_polling_is_last_and_gets_bot(mock_all):
    """start_polling gets bot and handle_signals=False."""
    from main import main

    mock_all["dp"].start_polling = AsyncMock()
    await main()

    mock_all["dp"].start_polling.assert_called_once()
    args, kwargs = mock_all["dp"].start_polling.call_args
    assert args[0] is mock_all["bot"]
    assert kwargs.get("handle_signals") is False


@pytest.mark.asyncio
async def test_exception_in_startup_triggers_cleanup(mock_all):
    """If init_db fails, cleanup is still called."""
    from main import main

    mock_all["init_db"].side_effect = RuntimeError("DB fail")

    with pytest.raises(RuntimeError, match="DB fail"):
        await main()

    mock_all["close_db"].assert_called_once()


@pytest.mark.asyncio
async def test_signal_path_graceful_shutdown_order(mock_all):
    """SIGINT triggers shutdown in correct order."""
    from main import main

    call_order = []

    async def fake_polling(*args, **kwargs):
        await asyncio.sleep(10)

    mock_all["dp"].start_polling.side_effect = fake_polling
    mock_all["scheduler"].shutdown.side_effect = lambda *a, **k: call_order.append("sched")
    mock_all["bot"].session.close.side_effect = lambda: call_order.append("bot")
    mock_all["runner"].cleanup.side_effect = lambda: call_order.append("health")
    mock_all["close_db"].side_effect = lambda: call_order.append("db")

    callbacks = {}

    class MockLoop:
        def add_signal_handler(self, sig, cb):
            callbacks[sig] = cb

    with patch("main.asyncio.get_running_loop", return_value=MockLoop()):
        main_task = asyncio.create_task(main())
        await asyncio.sleep(0.1)

        if signal.SIGINT in callbacks:
            callbacks[signal.SIGINT]()

        await main_task

    assert call_order == ["sched", "bot", "health", "db"]


@pytest.mark.asyncio
async def test_shutdown_exceptions_logged_not_raised(mock_all):
    """Errors in shutdown are logged, not propagated."""
    from main import main

    mock_all["dp"].start_polling = AsyncMock()
    mock_all["scheduler"].shutdown.side_effect = RuntimeError("sched fail")
    mock_all["close_db"].side_effect = RuntimeError("db fail")

    await main()

    error_calls = [c for c in mock_all["logger"].error.call_args_list if "Error" in str(c)]
    assert len(error_calls) >= 2


@pytest.mark.asyncio
async def test_main_completes_without_exceptions(mock_all):
    """Normal path completes cleanly."""
    from main import main

    mock_all["dp"].start_polling = AsyncMock()
    await main()


def test_if_name_main_guard():
    """Importing main does not run asyncio.run."""
    import main

    source = inspect.getsource(main)
    assert 'if __name__ == "__main__":' in source


@pytest.mark.asyncio
async def test_request_id_bound(mock_all):
    """request_id is generated and bound."""
    from main import main

    mock_all["dp"].start_polling = AsyncMock()
    await main()

    mock_all["new_request_id"].assert_called_once()
    mock_all["bind_contextvars"].assert_called_once_with(request_id="req-123")

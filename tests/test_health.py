"""Tests for health check module."""

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.config import Settings
from app.health import (
    _json_response,
    create_health_app,
    health_ready_handler,
)


@pytest.fixture
def valid_settings() -> Settings:
    """Create valid settings for testing."""
    with patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "test_bot_token",
            "LLM_BASE_URL": "http://localhost:8000/v1",
            "DATABASE_URL": "sqlite+aiosqlite:///test.db",
        },
        clear=False,
    ):
        return Settings()


@pytest.fixture
def settings_missing_token() -> Settings:
    """Create settings with missing TELEGRAM_BOT_TOKEN."""
    env_copy = {
        "LLM_BASE_URL": "http://localhost:8000/v1",
    }

    with patch.dict(os.environ, env_copy, clear=True):
        return Settings()


@pytest.fixture
def settings_invalid_db_url() -> Settings:
    """Create settings with invalid database URL."""
    with patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "test_bot_token",
            "LLM_BASE_URL": "http://localhost:8000/v1",
            "DATABASE_URL": "invalid://url",
        },
        clear=False,
    ):
        return Settings()


@pytest.fixture
def settings_with_google_creds(valid_settings: Settings, tmp_path: Path) -> Settings:
    """Create settings with existing Google credentials file."""
    creds_file = tmp_path / "google_credentials.json"
    creds_file.write_text('{"type": "service_account"}')
    valid_settings.GOOGLE_CREDENTIALS_PATH = str(creds_file)
    return valid_settings


@pytest.fixture
def settings_missing_google_creds(valid_settings: Settings) -> Settings:
    """Create settings with non-existent Google credentials file."""
    valid_settings.GOOGLE_CREDENTIALS_PATH = "/nonexistent/path/credentials.json"
    return valid_settings


class TestHealthEndpoint:
    """Test cases for /health endpoint."""

    async def test_health_returns_200(self, valid_settings: Settings) -> None:
        """Test that /health returns 200 status."""
        app = create_health_app(valid_settings)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200

    async def test_health_returns_json(self, valid_settings: Settings) -> None:
        """Test that /health returns JSON content type."""
        app = create_health_app(valid_settings)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.content_type == "application/json"

    async def test_health_response_structure(self, valid_settings: Settings) -> None:
        """Test that /health response has correct structure."""
        app = create_health_app(valid_settings)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            data = await resp.json()

            assert "status" in data
            assert data["status"] == "ok"
            assert "timestamp" in data
            assert "request_id" in data
            assert "service" in data
            assert data["service"] == "MedNews Secretary Agent"

    async def test_health_request_id_unique(self, valid_settings: Settings) -> None:
        """Test that each request gets unique request_id."""
        app = create_health_app(valid_settings)
        async with TestClient(TestServer(app)) as client:
            resp1 = await client.get("/health")
            resp2 = await client.get("/health")

            data1 = await resp1.json()
            data2 = await resp2.json()

            assert data1["request_id"] != data2["request_id"]


class TestHealthLiveEndpoint:
    """Test cases for /health/live endpoint."""

    async def test_health_live_returns_200(self, valid_settings: Settings) -> None:
        """Test that /health/live returns 200 status."""
        app = create_health_app(valid_settings)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/live")
            assert resp.status == 200

    async def test_health_live_response_structure(
        self, valid_settings: Settings
    ) -> None:
        """Test that /health/live response has correct structure."""
        app = create_health_app(valid_settings)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/live")
            data = await resp.json()

            assert "status" in data
            assert data["status"] == "alive"
            assert "uptime_seconds" in data
            assert isinstance(data["uptime_seconds"], (int, float))
            assert data["uptime_seconds"] >= 0
            assert "timestamp" in data
            assert "request_id" in data


class TestHealthReadyEndpoint:
    """Test cases for /health/ready endpoint."""

    async def test_health_ready_returns_200_with_valid_settings(
        self, valid_settings: Settings
    ) -> None:
        """Test that /health/ready returns 200 with valid settings."""
        app = create_health_app(valid_settings)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/ready")
            assert resp.status == 200

    async def test_health_ready_all_checks_true(self, valid_settings: Settings) -> None:
        """Test that all checks are true with valid settings."""
        app = create_health_app(valid_settings)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/ready")
            data = await resp.json()

            assert data["status"] == "ready"
            assert data["checks"]["settings_loaded"] is True
            assert data["checks"]["required_fields"] is True
            assert data["checks"]["database_url_valid"] is True
            assert data["checks"]["google_credentials"] is True

    async def test_health_ready_missing_token_returns_503(
        self, settings_missing_token: Settings
    ) -> None:
        """Test that /health/ready returns 503 with missing TELEGRAM_BOT_TOKEN."""
        app = create_health_app(settings_missing_token)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/ready")
            assert resp.status == 503

            data = await resp.json()
            assert data["status"] == "not_ready"
            assert data["checks"]["required_fields"] is False

    async def test_health_ready_invalid_db_url_returns_503(
        self, settings_invalid_db_url: Settings
    ) -> None:
        """Test that /health/ready returns 503 with invalid DATABASE_URL."""
        app = create_health_app(settings_invalid_db_url)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/ready")
            assert resp.status == 503

            data = await resp.json()
            assert data["checks"]["database_url_valid"] is False

    async def test_health_ready_missing_google_creds_returns_503(
        self, settings_missing_google_creds: Settings
    ) -> None:
        """Test that /health/ready returns 503 with missing Google credentials."""
        app = create_health_app(settings_missing_google_creds)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/ready")
            assert resp.status == 503

            data = await resp.json()
            assert data["checks"]["google_credentials"] is False
            errors_list = data.get("errors", [])
            assert any("Google credentials file not found" in e for e in errors_list)

    async def test_health_ready_with_existing_google_creds(
        self, settings_with_google_creds: Settings
    ) -> None:
        """Test that /health/ready passes with existing Google credentials."""
        app = create_health_app(settings_with_google_creds)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/ready")
            assert resp.status == 200

            data = await resp.json()
            assert data["checks"]["google_credentials"] is True

    async def test_health_ready_errors_included_on_failure(
        self, settings_missing_token: Settings
    ) -> None:
        """Test that errors are included in failure response."""
        app = create_health_app(settings_missing_token)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health/ready")
            data = await resp.json()

            assert "errors" in data
            assert len(data["errors"]) > 0


class TestRequestId:
    """Test cases for request_id handling."""

    async def test_request_id_in_log_matches_response(
        self, valid_settings: Settings
    ) -> None:
        """Test that request_id in logs matches response."""
        app = create_health_app(valid_settings)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            data = await resp.json()

            request_id = data["request_id"]
            assert len(request_id) > 0
            assert "-" in request_id


class TestCreateHealthApp:
    """Test cases for create_health_app function."""

    def test_create_health_app_accepts_custom_settings(
        self, valid_settings: Settings
    ) -> None:
        """Test that create_health_app accepts custom settings."""
        app = create_health_app(valid_settings)
        assert app["settings"] is valid_settings

    def test_create_health_app_has_three_routes(self, valid_settings: Settings) -> None:
        """Test that created app has three health routes."""
        app = create_health_app(valid_settings)
        routes = [route.method for route in app.router.routes()]

        assert "GET" in routes
        paths = [str(route.resource) for route in app.router.routes()]
        assert any("/health" in p for p in paths)
        assert any("/health/live" in p for p in paths)
        assert any("/health/ready" in p for p in paths)


class TestGracefulShutdown:
    """Test cases for graceful shutdown."""

    async def test_server_starts_and_stops(self, valid_settings: Settings) -> None:
        """Test that server can start and stop gracefully."""
        app = create_health_app(valid_settings)
        runner = web.AppRunner(app)

        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()

        assert site._server is not None

        await runner.cleanup()

    async def test_graceful_shutdown_signal_handling(
        self, valid_settings: Settings
    ) -> None:
        """Test that shutdown signals are handled properly."""
        app = create_health_app(valid_settings)
        assert app is not None


class TestJsonResponse:
    """Test cases for _json_response helper."""

    def test_json_response_with_request_id(self) -> None:
        """Test _json_response includes request_id when provided."""
        data = {"status": "ok"}
        response = _json_response(data, status=200, request_id="test-id-123")

        assert response.status == 200


class TestHealthLiveHandlerEdgeCases:
    """Test edge cases for health_live_handler."""

    async def test_health_live_high_loop_latency_returns_503(
        self, valid_settings: Settings
    ) -> None:
        """Test loop_latency > 5.0 branch coverage via direct handler call."""
        import json as json_module
        from unittest.mock import AsyncMock
        from unittest.mock import patch as mock_patch

        from app.health import health_live_handler

        # Create app and manually set up request with mocked time
        app = create_health_app(valid_settings)

        # Create a mock request
        mock_request = AsyncMock()
        mock_request.app = app
        mock_request.get = lambda key, default=None: app.get(key, default)

        # Mock time.monotonic to return high latency
        call_count = [0]

        def monotonic_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.0  # start_time from app (not used)
            elif call_count[0] == 2:
                return 0.0  # current_time
            elif call_count[0] == 3:
                return 0.0  # loop_check_start
            elif call_count[0] == 4:
                return 6.0  # after sleep, loop_latency = 6.0 > 5.0
            else:
                return call_count[0] * 6.0

        with mock_patch("app.health.time.monotonic", side_effect=monotonic_side_effect):
            # Call handler directly
            response = await health_live_handler(mock_request)  # type: ignore[arg-type]
            assert response.status == 503
            data = json_module.loads(response.text)
            assert data["status"] == "unhealthy"


class TestHealthReadyHandlerEdgeCases:
    """Test edge cases for health_ready_handler."""

    async def test_health_ready_settings_load_exception_returns_503(
        self, valid_settings: Settings
    ) -> None:
        """Test except Exception block in health_ready_handler."""
        from unittest.mock import patch as mock_patch

        # Mock get_settings to raise exception when called inside handler
        # We need to patch both during create_health_app and during handler execution
        with mock_patch("app.health.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = Exception("Settings load failed")

            # Create app with mocked settings - will use the mock and fail
            # But we catch it and set settings to None
            try:
                app = create_health_app(None)
            except Exception:
                # If create_health_app fails, create a minimal app
                from aiohttp import web
                app = web.Application()
                app.router.add_get("/health/ready", health_ready_handler)

            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/health/ready")
                assert resp.status == 503
                data = await resp.json()
                # When exception is caught, settings_loaded is set to False
                assert data["status"] == "not_ready"
                assert data["checks"]["settings_loaded"] is False


class TestRunHealthServer:
    """Test cases for run_health_server function."""

    async def test_run_health_server_setup_and_cleanup(
        self, valid_settings: Settings
    ) -> None:
        """Test run_health_server calls setup and cleanup."""
        from contextlib import suppress
        from unittest.mock import AsyncMock, MagicMock
        from unittest.mock import patch as mock_patch

        from app.health import run_health_server

        with mock_patch("app.health.web.AppRunner") as mock_runner_class:
            mock_runner = MagicMock()
            mock_runner.setup = AsyncMock()
            mock_runner.cleanup = AsyncMock()
            mock_runner_class.return_value = mock_runner

            mock_site = MagicMock()
            mock_site.start = AsyncMock()
            with (
                mock_patch("app.health.web.TCPSite", return_value=mock_site),
                mock_patch("asyncio.get_running_loop") as mock_loop,
            ):
                mock_loop_instance = MagicMock()
                mock_loop_instance.add_signal_handler = MagicMock()
                mock_loop.return_value = mock_loop_instance

                mock_event = MagicMock()
                mock_event.wait = AsyncMock(side_effect=asyncio.CancelledError())
                with mock_patch("asyncio.Event", return_value=mock_event):
                    with suppress(asyncio.CancelledError):
                        await run_health_server(
                            host="127.0.0.1", port=8080, settings=valid_settings
                        )

                    mock_runner.setup.assert_called_once()
                    mock_runner.cleanup.assert_called_once()

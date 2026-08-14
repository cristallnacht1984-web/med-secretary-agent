"""Health check server module for MedNews Secretary Agent.

Provides aiohttp-based health check endpoints for monitoring,
Docker health-check, and Kubernetes liveness/readiness probes.

"""

import asyncio
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import structlog
from aiohttp import web
from aiohttp.typedefs import Handler

from app.config import Settings, get_settings
from app.logging_setup import get_logger, new_request_id

logger = get_logger("health")

# Server start time for uptime calculation
_server_start_time: float | None = None


def _get_timestamp() -> str:
    """Get current UTC timestamp in ISO format.

    Returns:
        ISO formatted timestamp string.

    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_response(
    data: dict[str, Any],
    status: int = 200,
    request_id: str | None = None,
) -> web.Response:
    """Create JSON response with proper headers.

    Args:
        data: Response payload dictionary.
        status: HTTP status code (default: 200).
        request_id: Optional request ID to include in response.

    Returns:
        aiohttp web.Response with JSON body.

    """
    response_data = data.copy()
    if request_id:
        response_data["request_id"] = request_id
    return web.json_response(response_data, status=status)


async def _add_request_id_middleware(
    app: web.Application,
    handler: Handler,
) -> Handler:
    """Middleware to add request_id to each request context.

    Args:
        app: The aiohttp web.Application instance.
        handler: Request handler to call.

    Returns:
        Middleware handler function.

    """

    async def middleware_handler(request: web.Request) -> web.StreamResponse:
        """Inner handler that processes the request."""
        request_id = new_request_id()
        request["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        return await handler(request)

    return middleware_handler


async def health_handler(request: web.Request) -> web.Response:
    """Handle GET /health endpoint.

    Basic health check: application is alive.

    Args:
        request: aiohttp web.Request object.

    Returns:
        JSON response with status, timestamp, request_id, service.

    """
    request_id: str = request.get("request_id", new_request_id())
    timestamp = _get_timestamp()

    response_data = {
        "status": "ok",
        "timestamp": timestamp,
        "request_id": request_id,
        "service": "MedNews Secretary Agent",
    }
    return _json_response(response_data, status=200, request_id=request_id)


async def health_live_handler(request: web.Request) -> web.Response:
    """Handle GET /health/live endpoint.

    Liveness probe: checks if event loop is responsive.
    If event loop blocked > 5 seconds, returns 503.

    Args:
        request: aiohttp web.Request object.

    Returns:
        JSON response with status, uptime_seconds, timestamp, request_id.

    """
    request_id: str = request.get("request_id", new_request_id())
    timestamp = _get_timestamp()

    start_time: float = request.app.get("start_time", time.monotonic())
    current_time = time.monotonic()
    uptime_seconds = current_time - start_time

    # Check if event loop was blocked for too long
    loop_check_start = time.monotonic()
    await asyncio.sleep(0)  # Yield to event loop
    loop_latency = time.monotonic() - loop_check_start

    if loop_latency > 5.0:
        response_data = {
            "status": "unhealthy",
            "uptime_seconds": uptime_seconds,
            "timestamp": timestamp,
            "request_id": request_id,
        }
        return _json_response(response_data, status=503, request_id=request_id)

    response_data = {
        "status": "alive",
        "uptime_seconds": uptime_seconds,
        "timestamp": timestamp,
        "request_id": request_id,
    }
    return _json_response(response_data, status=200, request_id=request_id)


async def health_ready_handler(request: web.Request) -> web.Response:
    """Handle GET /health/ready endpoint.

    Readiness probe: checks if application is ready to serve traffic.
    Validates settings, required fields, database URL, and Google credentials.

    Args:
        request: aiohttp web.Request object.

    Returns:
        JSON response with status, checks, timestamp, request_id, and optional errors.

    """
    request_id: str = request.get("request_id", new_request_id())
    timestamp = _get_timestamp()

    checks: dict[str, bool] = {
        "settings_loaded": False,
        "required_fields": False,
        "database_url_valid": False,
        "google_credentials": True,  # Optional by default
    }
    errors: list[str] = []

    try:
        # Check 1: Settings loaded - get from app context first, then fallback
        settings: Settings = request.app.get("settings")
        if settings is None:
            settings = get_settings()
        checks["settings_loaded"] = True

        # Check 2: Required fields present
        required_fields = settings.validate_required_fields()
        if not required_fields:
            checks["required_fields"] = True
        else:
            for field in required_fields:
                errors.append(f"Missing required field: {field}")

        # Check 3: Database URL valid (parse only, no connection)
        db_url = settings.DATABASE_URL
        if db_url:
            try:
                parsed = urlparse(db_url)
                known_schemes = {
                    "sqlite",
                    "sqlite+aiosqlite",
                    "postgresql",
                    "postgresql+asyncpg",
                    "mysql",
                    "mysql+aiomysql",
                }
                has_valid_format = (
                    parsed.scheme in known_schemes and (parsed.netloc or parsed.path)
                )
                if has_valid_format:
                    checks["database_url_valid"] = True
                else:
                    checks["database_url_valid"] = False
                    errors.append("Invalid database URL format")
            except Exception:
                checks["database_url_valid"] = False
                errors.append("Failed to parse database URL")
        else:
            # No database URL configured - consider valid (optional)
            checks["database_url_valid"] = True

        # Check 4: Google credentials file exists (if path specified)
        google_creds_path = settings.GOOGLE_CREDENTIALS_PATH
        if google_creds_path:
            creds_file = Path(google_creds_path)
            if creds_file.exists():
                checks["google_credentials"] = True
            else:
                checks["google_credentials"] = False
                errors.append("Google credentials file not found")
        # If no path specified, google_credentials stays True (optional)

    except Exception as e:
        checks["settings_loaded"] = False
        errors.append(f"Failed to load settings: {e!s}")

    # Determine overall status
    all_checks_passed = all(checks.values()) and len(errors) == 0

    if all_checks_passed:
        response_data = {
            "status": "ready",
            "checks": checks,
            "timestamp": timestamp,
            "request_id": request_id,
        }
        return _json_response(response_data, status=200, request_id=request_id)
    else:
        response_data = {
            "status": "not_ready",
            "checks": checks,
            "errors": errors,
            "timestamp": timestamp,
            "request_id": request_id,
        }
        return _json_response(response_data, status=503, request_id=request_id)


def create_health_app(
    settings: Settings | None = None, time_provider: Callable[[], float] | None = None
) -> web.Application:
    """Create aiohttp web.Application with health check endpoints.

    Args:
        settings: Optional Settings instance. If None, uses get_settings().
        time_provider: Optional function to provide current time (for testing).

    Returns:
        Configured aiohttp web.Application with three health endpoints.

    """
    if settings is None:
        settings = get_settings()

    app = web.Application(middlewares=[_add_request_id_middleware])
    app["settings"] = settings
    app["start_time"] = (
        time_provider() if time_provider is not None else time.monotonic()
    )

    app.router.add_get("/health", health_handler)
    app.router.add_get("/health/live", health_live_handler)
    app.router.add_get("/health/ready", health_ready_handler)

    return app


async def run_health_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    settings: Settings | None = None,
) -> None:
    """Run the health check aiohttp server with graceful shutdown.

    Args:
        host: Host address to bind to (default: "0.0.0.0").
        port: Port number to bind to (default: 8080).
        settings: Optional Settings instance.

    """
    global _server_start_time

    app = create_health_app(settings)
    runner = web.AppRunner(app)

    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    _server_start_time = time.monotonic()
    logger.info(f"Health server started on {host}:{port}")

    # Setup graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal(sig: int) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {sig}, initiating shutdown")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    try:
        await shutdown_event.wait()
    finally:
        logger.info("Shutting down health server")
        await runner.cleanup()
        logger.info("Health server stopped")

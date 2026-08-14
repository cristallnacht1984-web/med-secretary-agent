"""Health check module for MedNews Secretary Agent."""
import asyncio
import signal
from typing import Any

from aiohttp import web

from app.config import get_settings
from app.logging_setup import get_logger, new_request_id

logger = get_logger("health")


async def health_handler(request: web.Request) -> web.Response:
    """Handle /health endpoint - basic availability check."""
    return web.json_response({"status": "ok"})


async def health_live_handler(request: web.Request) -> web.Response:
    """Handle /health/live endpoint - liveness probe with loop latency check."""
    # Check event loop latency
    loop = asyncio.get_event_loop()
    start = loop.time()
    await asyncio.sleep(0)
    latency = loop.time() - start

    # Threshold: 5.0 seconds indicates a blocked loop
    if latency > 5.0:
        logger.warning("Event loop latency too high", latency=latency)
        return web.json_response(
            {"status": "unhealthy", "reason": "loop_latency", "latency": latency},
            status=503,
        )

    return web.json_response({"status": "alive", "latency": latency})


async def health_ready_handler(request: web.Request) -> web.Response:
    """Handle /health/ready endpoint - readiness probe checking dependencies."""
    settings = get_settings()
    errors: list[str] = []

    # Check required settings
    if not settings.TELEGRAM_BOT_TOKEN.get_secret_value():
        errors.append("TELEGRAM_BOT_TOKEN missing")

    # Check database URL format
    if not settings.DATABASE_URL:
        errors.append("DATABASE_URL missing")

    # Check Google credentials if calendar is used
    if not settings.GOOGLE_CREDENTIALS_JSON:
        logger.info("Google credentials not configured")

    if errors:
        logger.warning("Readiness check failed", errors=errors)
        return web.json_response(
            {"status": "not_ready", "errors": errors},
            status=503,
        )

    return web.json_response({"status": "ready"})


@web.middleware
async def request_id_middleware(
    request: web.Request, handler: Any
) -> web.StreamResponse:
    """Middleware to generate and propagate request_id."""
    new_request_id()
    response = await handler(request)
    return response


async def create_app() -> web.Application:
    """Create and configure the health check web application."""
    settings = get_settings()

    app = web.Application(middlewares=[request_id_middleware])
    app.router.add_get("/health", health_handler)
    app.router.add_get("/health/live", health_live_handler)
    app.router.add_get("/health/ready", health_ready_handler)

    logger.info(
        "Health check server configured",
        host=settings.HEALTH_CHECK_HOST,
        port=settings.HEALTH_CHECK_PORT,
    )

    return app


async def run_health_server(app: web.Application) -> None:
    """Run the health check server until shutdown signal."""
    settings = get_settings()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, settings.HEALTH_CHECK_HOST, settings.HEALTH_CHECK_PORT)
    await site.start()

    logger.info(
        "Health check server started",
        host=settings.HEALTH_CHECK_HOST,
        port=settings.HEALTH_CHECK_PORT,
    )

    # Wait for shutdown signals
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("Shutting down health check server")
    await runner.cleanup()

"""Main entry point for MedNews Secretary Agent."""
import asyncio
import signal

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
from structlog.contextvars import bind_contextvars

from app.bot.router import build_router
from app.config import get_settings
from app.db import close_db, init_db
from app.health import create_app
from app.logging_setup import get_logger, new_request_id, setup_logging
from app.scheduler import build_scheduler


async def _graceful_shutdown(
    scheduler,
    bot,
    health_runner,
    logger,
) -> None:
    """Execute graceful shutdown in strict order. Never raises exceptions."""
    if scheduler is not None:
        try:
            logger.info("Shutting down scheduler...")
            await scheduler.shutdown(wait=True)
        except Exception as e:
            logger.error("Error shutting down scheduler", error=str(e))

    if bot is not None:
        try:
            logger.info("Closing bot session...")
            await bot.session.close()
        except Exception as e:
            logger.error("Error closing bot session", error=str(e))

    if health_runner is not None:
        try:
            logger.info("Shutting down health server...")
            await health_runner.cleanup()
        except Exception as e:
            logger.error("Error shutting down health server", error=str(e))

    try:
        logger.info("Closing database...")
        await close_db()
    except Exception as e:
        logger.error("Error closing database", error=str(e))


async def main() -> None:
    """Entry point. STARTUP ORDER + graceful shutdown."""
    settings = get_settings()
    setup_logging()

    logger = get_logger("main")
    request_id = new_request_id()
    bind_contextvars(request_id=request_id)

    logger.info("Starting MedNews Secretary Agent")

    scheduler = None
    bot = None
    health_runner = None
    polling_task = None
    stop_task = None

    try:
        # 1. Health server (non-blocking setup)
        health_app = await create_app()
        health_runner = web.AppRunner(health_app)
        await health_runner.setup()
        site = web.TCPSite(
            health_runner,
            settings.HEALTH_CHECK_HOST,
            settings.HEALTH_CHECK_PORT,
        )
        await site.start()

        # 2. Database
        await init_db()

        # 3. Bot & Dispatcher
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())
        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher.include_router(build_router())

        # 4. Scheduler
        scheduler = build_scheduler(settings)
        scheduler.start()

        # 5. Signals
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                logger.warning("Signal handler not supported", signal=sig)

        # 6. Polling
        polling_task = asyncio.create_task(
            dispatcher.start_polling(bot, handle_signals=False)
        )
        stop_task = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait(
            {polling_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if polling_task in done and polling_task.exception():
            raise polling_task.exception()

    except Exception:
        logger.exception("Critical error in main loop")
        raise
    finally:
        if stop_task and not stop_task.done():
            stop_task.cancel()
        if polling_task and not polling_task.done():
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass

        await _graceful_shutdown(scheduler, bot, health_runner, logger)
        logger.info("MedNews Secretary Agent stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

"""Database engine and session management for MedNews Secretary Agent."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.logging_setup import get_logger

logger = get_logger("db")

_engine = None
_async_session_factory = None


def _get_engine():
    """Lazy initialization of the database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
    return _engine


def _get_session_factory():
    """Lazy initialization of the session factory."""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(_get_engine(), expire_on_commit=False)
    return _async_session_factory


async def init_db() -> None:
    """Initialize database by creating all tables."""
    logger.info("Initializing database...")
    engine = _get_engine()
    from app.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully.")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for dependency injection."""
    session_factory = _get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    """Close database connections gracefully."""
    logger.info("Closing database connections...")
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    logger.info("Database connections closed.")

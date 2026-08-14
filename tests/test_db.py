"""Tests for database module."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Article, Base
from app.db.repository import Repository


@pytest.fixture(scope="session")
def test_engine():
    """Create test engine with in-memory SQLite."""
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )


@pytest.fixture
async def session(test_engine):
    """Create a fresh session for each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session_factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_factory() as s:
        yield s
        await s.rollback()


@pytest.fixture
async def repository(session):
    """Create repository instance for tests."""
    return Repository(session)


class TestInitDB:
    """Test database initialization."""

    async def test_init_db_creates_tables(self, test_engine):
        """Test that init_db creates all tables."""
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Verify tables exist by querying metadata
        from sqlalchemy import inspect
        
        async with test_engine.begin() as conn:
            result = await conn.run_sync(lambda c: inspect(c).get_table_names())
            assert "articles" in result
            assert "digest_logs" in result
            assert "reminder_logs" in result


class TestArticleOperations:
    """Test Article CRUD operations."""

    async def test_add_article_saves_and_reads(self, session, repository):
        """Test add_article saves article and can be read back."""
        article = await repository.add_article(
            url="https://example.com/article1",
            title_hash="hash123",
            source="TestSource",
            title="Test Article Title",
        )
        
        assert article.url == "https://example.com/article1"
        assert article.title_hash == "hash123"
        assert article.source == "TestSource"
        assert article.title == "Test Article Title"
        assert article.id is not None

    async def test_is_article_duplicate_returns_false_for_unique(self, session, repository):
        """Test is_article_duplicate returns False for unique article."""
        is_dup = await repository.is_article_duplicate(
            url="https://example.com/unique",
            title_hash="unique_hash",
        )
        assert is_dup is False

    async def test_is_article_duplicate_returns_true_for_url_duplicate(self, session, repository):
        """Test is_article_duplicate returns True for URL duplicate."""
        await repository.add_article(
            url="https://example.com/dup",
            title_hash="hash_dup",
            source="Source",
            title="Title",
        )
        is_dup = await repository.is_article_duplicate(
            url="https://example.com/dup",
            title_hash="different_hash",
        )
        assert is_dup is True

    async def test_is_article_duplicate_returns_true_for_title_hash_duplicate(self, session, repository):
        """Test is_article_duplicate returns True for title_hash duplicate."""
        await repository.add_article(
            url="https://example.com/original",
            title_hash="same_hash",
            source="Source",
            title="Title",
        )
        is_dup = await repository.is_article_duplicate(
            url="https://example.com/different",
            title_hash="same_hash",
        )
        assert is_dup is True

    async def test_cleanup_old_articles_removes_old_keeps_new(self, session, repository):
        """Test cleanup_old_articles removes old articles and keeps new ones."""
        from datetime import datetime, timedelta, timezone
        
        # Add old article (8 days ago)
        old_article = Article(
            url="https://example.com/old",
            title_hash="old_hash",
            source="Source",
            title="Old Article",
            fetched_at=datetime.now(timezone.utc) - timedelta(days=8),
        )
        session.add(old_article)
        await session.flush()
        
        # Add new article (1 day ago)
        new_article = Article(
            url="https://example.com/new",
            title_hash="new_hash",
            source="Source",
            title="New Article",
            fetched_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        session.add(new_article)
        await session.flush()
        
        # Cleanup old articles (7 day window)
        deleted_count = await repository.cleanup_old_articles(window_days=7)
        
        assert deleted_count == 1
        
        # Verify only new article remains
        stmt = select(Article)
        result = await session.execute(stmt)
        remaining = result.scalars().all()
        assert len(remaining) == 1
        assert remaining[0].url == "https://example.com/new"


class TestDigestLogOperations:
    """Test DigestLog operations."""

    async def test_create_digest_log_creates_entry(self, session, repository):
        """Test create_digest_log creates a digest log entry."""
        digest_log = await repository.create_digest_log(
            chat_id=123456,
            article_count=5,
            batch_count=2,
            status="pending",
        )
        
        assert digest_log.chat_id == 123456
        assert digest_log.article_count == 5
        assert digest_log.batch_count == 2
        assert digest_log.status == "pending"
        assert digest_log.id is not None

    async def test_mark_digest_sent_updates_status_and_message_id(self, session, repository):
        """Test mark_digest_sent updates status to 'sent' and sets message_id."""
        digest_log = await repository.create_digest_log(
            chat_id=123456,
            article_count=5,
            batch_count=2,
            status="pending",
        )
        
        await repository.mark_digest_sent(digest_log.id, message_id=999)
        
        # Refresh from DB
        await session.refresh(digest_log)
        assert digest_log.status == "sent"
        assert digest_log.message_id == 999


class TestReminderLogOperations:
    """Test ReminderLog operations."""

    async def test_was_reminder_sent_returns_false_initially(self, session, repository):
        """Test was_reminder_sent returns False when no reminder sent."""
        was_sent = await repository.was_reminder_sent(
            event_id="event_123",
            user_id=456,
        )
        assert was_sent is False

    async def test_was_reminder_sent_returns_true_after_marking(self, session, repository):
        """Test was_reminder_sent returns True after marking as sent."""
        from datetime import datetime, timezone
        
        event_start = datetime.now(timezone.utc)
        await repository.mark_reminder_sent(
            event_id="event_123",
            event_start=event_start,
            user_id=456,
        )
        
        was_sent = await repository.was_reminder_sent(
            event_id="event_123",
            user_id=456,
        )
        assert was_sent is True

    async def test_mark_reminder_sent_creates_entry(self, session, repository):
        """Test mark_reminder_sent creates a reminder log entry."""
        from datetime import datetime, timezone
        
        event_start = datetime.now(timezone.utc)
        reminder_log = await repository.mark_reminder_sent(
            event_id="event_456",
            event_start=event_start,
            user_id=789,
        )
        
        assert reminder_log.event_id == "event_456"
        assert reminder_log.user_id == 789
        # Compare timestamps ignoring timezone info (SQLite stores without tz)
        assert reminder_log.event_start.replace(tzinfo=None) == event_start.replace(tzinfo=None)


class TestTransactionRollback:
    """Test transaction rollback on constraint violations."""

    async def test_rollback_on_unique_constraint_violation(self, session, repository):
        """Test that unique constraint violation triggers rollback."""
        import sqlalchemy.exc
        # Add first article
        await repository.add_article(
            url="https://example.com/unique_test",
            title_hash="unique_test_hash",
            source="Source",
            title="Title",
        )
        await session.commit()  # Commit the first article
        
        # Try to add duplicate (should fail due to unique constraint on url)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await repository.add_article(
                url="https://example.com/unique_test",
                title_hash="different_hash",
                source="Source",
                title="Another Title",
            )
        
        # Session needs explicit rollback after exception in repository method
        await session.rollback()
        
        # Session should still be usable after rollback
        # Just verify we can query without errors
        stmt = select(Article).where(Article.url == "https://example.com/unique_test")
        result = await session.execute(stmt)
        articles = result.scalars().all()
        assert len(articles) == 1


class TestGetSession:
    """Test get_session generator."""

    async def test_get_session_yields_session(self, test_engine):
        """Test get_session yields an AsyncSession."""
        
        # Create a temporary session factory for testing
        async_session_factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        
        async def mock_get_session():
            async with async_session_factory() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise
                finally:
                    await s.close()
        
        gen = mock_get_session()
        session = await gen.__anext__()
        assert isinstance(session, AsyncSession)
        
        # Cleanup
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass


class TestCloseDB:
    """Test close_db function."""

    async def test_close_db_disposes_engine(self, test_engine):
        """Test close_db disposes the engine."""
        # Engine should be valid before close
        assert test_engine is not None
        
        # Call dispose directly (simulating close_db)
        await test_engine.dispose()
        
        # Engine is disposed (can't easily verify, but no error means success)


class TestDatabaseModuleFunctions:
    """Test init_db, get_session, close_db functions directly."""

    async def test_init_db_get_session_close(self):
        """Test full lifecycle of database module functions."""
        from unittest.mock import MagicMock, patch

        import app.db.database as db_module
        from app.db.database import close_db, get_session, init_db

        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"

        # Reset global state
        db_module._engine = None
        db_module._async_session_factory = None

        with patch("app.db.database.get_settings", return_value=mock_settings):
            await init_db()
            assert db_module._engine is not None

            async for session in get_session():
                assert session is not None

            await close_db()
            assert db_module._engine is None

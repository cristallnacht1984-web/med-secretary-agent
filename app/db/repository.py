"""Repository pattern for database operations."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Article, DigestLog, ReminderLog


class Repository:
    """Async repository for CRUD operations on database models."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_article(
        self, url: str, title_hash: str, source: str, title: str
    ) -> Article:
        """Add a new article to the database."""
        article = Article(
            url=url,
            title_hash=title_hash,
            source=source,
            title=title,
            fetched_at=datetime.now(timezone.utc),
        )
        self.session.add(article)
        await self.session.flush()
        await self.session.refresh(article)
        return article

    async def is_article_duplicate(self, url: str, title_hash: str) -> bool:
        """Check if an article with the given URL or title_hash already exists."""
        stmt = select(Article).where(
            (Article.url == url) | (Article.title_hash == title_hash)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def cleanup_old_articles(self, window_days: int = 7) -> int:
        """Delete articles older than window_days. Returns count of deleted articles."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=window_days)
        stmt = delete(Article).where(Article.fetched_at < cutoff_date)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0

    async def create_digest_log(
        self,
        chat_id: int,
        article_count: int,
        batch_count: int,
        status: str = "pending",
        error_message: str | None = None,
    ) -> DigestLog:
        """Create a new digest log entry."""
        digest_log = DigestLog(
            sent_at=datetime.now(timezone.utc),
            chat_id=chat_id,
            article_count=article_count,
            batch_count=batch_count,
            status=status,
            error_message=error_message,
        )
        self.session.add(digest_log)
        await self.session.flush()
        await self.session.refresh(digest_log)
        return digest_log

    async def mark_digest_sent(self, digest_id: int, message_id: int) -> None:
        """Mark a digest log as sent with the message ID."""
        stmt = select(DigestLog).where(DigestLog.id == digest_id)
        result = await self.session.execute(stmt)
        digest_log = result.scalar_one_or_none()
        if digest_log:
            digest_log.status = "sent"
            digest_log.message_id = message_id
            await self.session.flush()

    async def was_reminder_sent(self, event_id: str, user_id: int) -> bool:
        """Check if a reminder was already sent for the given event and user."""
        stmt = select(ReminderLog).where(
            (ReminderLog.event_id == event_id) & (ReminderLog.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def mark_reminder_sent(
        self, event_id: str, event_start: datetime, user_id: int
    ) -> ReminderLog:
        """Mark a reminder as sent by creating a log entry."""
        reminder_log = ReminderLog(
            event_id=event_id,
            event_start=event_start,
            sent_at=datetime.now(timezone.utc),
            user_id=user_id,
        )
        self.session.add(reminder_log)
        await self.session.flush()
        await self.session.refresh(reminder_log)
        return reminder_log

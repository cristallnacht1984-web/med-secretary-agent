"""Services package for MedNews Secretary Agent."""
from app.services.calendar_service import CalendarAuthError, CalendarService
from app.services.digest_builder import (
    REGION_EMOJI,
    DigestDeliveryError,
    build_digest_message,
    escape_markdown_v2,
    format_digest_markdown,
    send_digest_to_telegram,
)
from app.services.news_pipeline import (
    build_batches,
    deduplicate_articles,
    prepare_batches_for_analysis,
)
from app.services.reminder_engine import ReminderEngine
from app.services.rss_fetcher import (
    RSS_FEEDS,
    FeedFetchError,
    RawArticle,
    fetch_all_feeds,
    fetch_single_feed,
)

__all__ = [
    "RawArticle",
    "FeedFetchError",
    "fetch_all_feeds",
    "fetch_single_feed",
    "RSS_FEEDS",
    "deduplicate_articles",
    "build_batches",
    "prepare_batches_for_analysis",
    "DigestDeliveryError",
    "REGION_EMOJI",
    "build_digest_message",
    "escape_markdown_v2",
    "format_digest_markdown",
    "send_digest_to_telegram",
    "CalendarService",
    "CalendarAuthError",
    "ReminderEngine",
]

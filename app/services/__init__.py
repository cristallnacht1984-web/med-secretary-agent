"""Services package for MedNews Secretary Agent."""
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
]

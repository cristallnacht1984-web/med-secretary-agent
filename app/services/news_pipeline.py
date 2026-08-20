"""News Pipeline Service for MedNews Secretary Agent.

Provides deduplication and batching functionality for RSS articles before LLM analysis.
Async-first implementation with graceful error handling.
"""
import hashlib
from typing import Any

from structlog import get_logger

from app.config import get_settings
from app.db.database import get_session
from app.db.repository import Repository
from app.logging_setup import new_request_id
from app.services.rss_fetcher import RawArticle, fetch_all_feeds


def _compute_title_hash(title: str) -> str:
    """Compute MD5 hash of article title for deduplication."""
    return hashlib.md5(title.encode()).hexdigest()


async def deduplicate_articles(articles: list[RawArticle]) -> list[RawArticle]:
    """Remove duplicate articles based on URL and title hash.

    For each article:
    1. Compute title_hash = hashlib.md5(title.encode()).hexdigest()
    2. Check is_article_duplicate(url, title_hash) - discard if duplicate
    3. Save unique articles via add_article(url, title_hash, source, title, fetched_at=<UTC now>)

    Args:
        articles: List of raw articles from RSS fetcher

    Returns:
        List of unique articles (duplicates removed).
        Empty list if database error occurs (graceful degradation).
    """
    request_id = new_request_id()
    logger = get_logger("news")
    unique_articles: list[RawArticle] = []

    try:
        # get_session is an async generator, use async for to get the session
        async for session in get_session():
            repo = Repository(session)

            for article in articles:
                title_hash = _compute_title_hash(article.title)

                # Check if duplicate
                is_dup = await repo.is_article_duplicate(article.url, title_hash)

                if not is_dup:
                    # Save unique article to DB
                    await repo.add_article(
                        url=article.url,
                        title_hash=title_hash,
                        source=article.source,
                        title=article.title,
                    )
                    unique_articles.append(article)
                else:
                    logger.debug(
                        "Duplicate article skipped",
                        extra={
                            "url": article.url,
                            "title": article.title[:50],
                            "request_id": request_id,
                        },
                    )

        logger.info(
            "Deduplication completed",
            extra={
                "input_count": len(articles),
                "unique_count": len(unique_articles),
                "duplicates_removed": len(articles) - len(unique_articles),
                "request_id": request_id,
            },
        )
        return unique_articles

    except Exception as e:
        logger.error(
            "Database error during deduplication - returning empty list",
            extra={"error": str(e), "request_id": request_id},
        )
        # Graceful degradation: return empty list, don't crash pipeline
        return []


def build_batches(articles: list[RawArticle]) -> list[list[RawArticle]]:
    """Split articles into batches for LLM analysis.

    Batch sizing rules:
    - Use NEWS_BATCH_MIN and NEWS_BATCH_MAX from settings
    - Split by NEWS_BATCH_MAX
    - Last batch can be smaller than MIN (1-2 articles included)
    - If total articles < NEWS_BATCH_MIN: single batch with all articles
    - Empty input returns empty result

    Args:
        articles: List of unique articles after deduplication

    Returns:
        List of batches, where each batch is a list of articles.
        Example: 10 articles -> [[5], [5]], 7 articles -> [[5], [2]]
    """
    if not articles:
        return []

    settings = get_settings()
    batch_min = settings.NEWS_BATCH_MIN
    batch_max = settings.NEWS_BATCH_MAX

    # If total articles < MIN, return single batch with all
    if len(articles) < batch_min:
        return [articles]

    # Split by batch_max
    batches: list[list[RawArticle]] = []
    for i in range(0, len(articles), batch_max):
        batch = articles[i : i + batch_max]
        batches.append(batch)

    logger = get_logger("news")
    logger.info(
        "Batches built",
        extra={
            "total_articles": len(articles),
            "batch_count": len(batches),
            "batch_sizes": [len(b) for b in batches],
        },
    )

    return batches


async def prepare_batches_for_analysis(lookback_hours: int = 24) -> list[list[dict[str, Any]]]:
    """Full pipeline: fetch RSS → deduplicate → batch → convert to dict for LLM.

    Pipeline steps:
    1. Fetch all RSS feeds (lookback_hours)
    2. Deduplicate articles (via deduplicate_articles)
    3. Build batches (via build_batches)
    4. Convert each article to dict with keys: url, title, content, source

    Args:
        lookback_hours: Hours to look back for RSS fetching (default 24)

    Returns:
        List of batches, where each batch is a list of dicts with keys:
        url, title, content, source
        Ready for LLM client consumption.
    """
    request_id = new_request_id()
    logger = get_logger("news")
    logger.info(
        "Starting prepare_batches_for_analysis",
        extra={"lookback_hours": lookback_hours, "request_id": request_id},
    )

    # Step 1: Fetch RSS feeds
    raw_articles = await fetch_all_feeds(lookback_hours=lookback_hours)

    if not raw_articles:
        logger.warning("No articles fetched from RSS feeds", extra={"request_id": request_id})
        return []

    logger.info(
        "Fetched articles from RSS",
        extra={"count": len(raw_articles), "request_id": request_id},
    )

    # Step 2: Deduplicate
    unique_articles = await deduplicate_articles(raw_articles)

    if not unique_articles:
        logger.warning("No unique articles after deduplication", extra={"request_id": request_id})
        return []

    # Step 3: Build batches
    batches = build_batches(unique_articles)

    if not batches:
        logger.warning("No batches built", extra={"request_id": request_id})
        return []

    # Step 4: Convert to dict format for LLM
    result: list[list[dict[str, Any]]] = []
    for batch in batches:
        dict_batch = [
            {
                "url": article.url,
                "title": article.title,
                "content": article.content,
                "source": article.source,
            }
            for article in batch
        ]
        result.append(dict_batch)

    logger.info(
        "prepare_batches_for_analysis completed",
        extra={
            "batch_count": len(result),
            "total_articles": sum(len(b) for b in result),
            "request_id": request_id,
        },
    )

    return result

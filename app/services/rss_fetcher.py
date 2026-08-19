"""RSS Feed Fetcher for MedNews Secretary Agent.

Async-first RSS fetcher with retry/backoff, graceful failure, and date filtering.
Uses aiohttp for HTTP requests and feedparser for RSS parsing.
"""
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp
import feedparser
from structlog import get_logger

from app.config import get_settings
from app.logging_setup import new_request_id


@dataclass
class RawArticle:
    """Сырая статья из RSS-фида."""

    url: str
    title: str
    content: str
    source: str
    region: str
    published_at: datetime


class FeedFetchError(Exception):
    """Выбрасывается, если все retry для фида исчерпаны."""

    pass


# Список RSS фидов (хардкод константа)
RSS_FEEDS: list[tuple[str, str, str]] = [
    ("https://www.statnews.com/feed/", "STAT News", "Америка"),
    ("https://www.medscape.com/rss/all.xml", "Medscape", "Америка"),
    ("https://www.thelancet.com/rss/news.xml", "The Lancet News", "Европа"),
    ("https://www.fiercebiotech.com/rss/xml", "Fierce Biotech", "Европа"),
    ("https://medvestnik.ru/rss/", "Медвестник", "Россия"),
    ("https://pharmvestnik.ru/rss/", "Pharmvestnik", "Россия"),
    ("https://www.nature.com/nm.rss", "Nature Medicine Asia", "Азия"),
    ("https://www.channelnewsasia.com/rss/health", "CNA Health", "Азия"),
    ("https://www.who.int/rss-feeds/news-english.xml", "WHO Newsroom", "Глобал"),
    ("https://www.reuters.com/health/rss", "Reuters Health", "Глобал"),
]


async def _parse_feed_async(xml_content: str) -> Any:
    """Парсинг RSS в отдельном потоке чтобы не блокировать event loop."""
    return await asyncio.to_thread(feedparser.parse, xml_content)


def _parse_published_date(date_str: str | None) -> datetime | None:
    """Парсинг даты публикации из RSS."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        # Конвертируем в UTC для сравнения
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


async def _fetch_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    source: str,
    region: str,
    lookback_hours: int,
    logger: Any,
    request_id: str,
) -> list[RawArticle]:
    """Fetch single feed with exponential backoff retry."""
    settings = get_settings()
    timeout_seconds = getattr(settings, "FETCH_TIMEOUT_SECONDS", 30.0)
    max_retries = getattr(settings, "FETCH_MAX_RETRIES", 3)
    base_delay = 1.0

    articles: list[RawArticle] = []
    last_exception: Exception | None = None

    for attempt in range(max_retries):
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with session.get(url, timeout=timeout) as response:
                if response.status >= 500:
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message=f"Server error: {response.status}",
                    )

                if response.status == 404:
                    logger.warning(
                        "Feed not found (404)",
                        extra={
                            "url": url,
                            "source": source,
                            "request_id": request_id,
                        },
                    )
                    return []

                response.raise_for_status()
                xml_content = await response.text()

                # Парсинг в отдельном потоке
                feed_data = await _parse_feed_async(xml_content)

                if feed_data.bozo:
                    logger.warning(
                        "Malformed RSS feed",
                        extra={
                            "url": url,
                            "source": source,
                            "error": str(feed_data.bozo_exception),
                            "request_id": request_id,
                        },
                    )

                cutoff_time = datetime.now(UTC).replace(
                    hour=datetime.now(UTC).hour
                )
                from datetime import timedelta

                cutoff_time = datetime.now(UTC) - timedelta(hours=lookback_hours)

                for entry in feed_data.entries:
                    published_raw = entry.get("published") or entry.get("updated")
                    published_at = _parse_published_date(published_raw)

                    if published_at is None:
                        # Если дата не распарсилась, пропускаем статью
                        continue

                    # Фильтрация по дате (только последние lookback_hours)
                    if published_at < cutoff_time:
                        continue

                    # Извлекаем контент
                    content = ""
                    if hasattr(entry, "content") and entry.content:
                        content = entry.content[0].get("value", "")
                    elif hasattr(entry, "summary"):
                        content = entry.summary
                    elif hasattr(entry, "description"):
                        content = entry.description

                    # Получаем URL статьи
                    article_url = entry.get("link", "")
                    if not article_url:
                        continue

                    title = entry.get("title", "")

                    article = RawArticle(
                        url=article_url,
                        title=title,
                        content=content,
                        source=source,
                        region=region,
                        published_at=published_at,
                    )
                    articles.append(article)

                logger.info(
                    f"Successfully fetched {len(articles)} articles from {source}",
                    extra={"url": url, "source": source, "request_id": request_id},
                )
                return articles

        except (TimeoutError, aiohttp.ClientError) as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"Retry {attempt + 1}/{max_retries} after {delay}s",
                    extra={
                        "url": url,
                        "source": source,
                        "error": str(e),
                        "attempt": attempt + 1,
                        "request_id": request_id,
                    },
                )
                await asyncio.sleep(delay)
            else:
                break

    # Все retry исчерпаны
    logger.warning(
        "All retries exhausted for feed",
        extra={
            "url": url,
            "source": source,
            "error": str(last_exception) if last_exception else "Unknown error",
            "request_id": request_id,
        },
    )
    raise FeedFetchError(
        f"Failed to fetch feed {url} after {max_retries} retries: {last_exception}"
    )


async def fetch_single_feed(
    url: str, source: str, region: str, lookback_hours: int = 24
) -> list[RawArticle]:
    """Собрать статьи из одного RSS-фида.

    Args:
        url: URL RSS фида
        source: Название источника
        region: Регион источника
        lookback_hours: Период.lookback в часах (default 24)

    Returns:
        list[RawArticle]: Список статей из фида

    Raises:
        FeedFetchError: Если все retry исчерпаны
    """
    request_id = new_request_id()
    logger = get_logger("rss")

    async with aiohttp.ClientSession() as session:
        try:
            articles = await _fetch_with_retry(
                session=session,
                url=url,
                source=source,
                region=region,
                lookback_hours=lookback_hours,
                logger=logger,
                request_id=request_id,
            )
            return articles
        except FeedFetchError:
            raise
        except Exception as e:
            logger.warning(
                "Unexpected error fetching feed",
                extra={
                    "url": url,
                    "source": source,
                    "error": str(e),
                    "request_id": request_id,
                },
            )
            raise FeedFetchError(f"Failed to fetch feed {url}: {e}") from e


async def fetch_all_feeds(lookback_hours: int = 24) -> list[RawArticle]:
    """Собрать статьи из всех 10 RSS-источников за последние lookback_hours.

    Args:
        lookback_hours: Период lookback в часах (default 24)

    Returns:
        list[RawArticle]: Список всех статей из всех фидов.
                         Пустой список если все фиды упали.
    """
    request_id = new_request_id()
    logger = get_logger("rss")
    logger.info(
        "Starting to fetch all feeds",
        extra={"lookback_hours": lookback_hours, "request_id": request_id},
    )

    all_articles: list[RawArticle] = []
    failed_feeds: list[str] = []

    tasks = []
    for url, source, region in RSS_FEEDS:
        task = _fetch_feed_wrapper(url, source, region, lookback_hours, logger, request_id)
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        url, source, region = RSS_FEEDS[i]
        if isinstance(result, Exception):
            failed_feeds.append(source)
            logger.warning(
                "Feed failed",
                extra={
                    "url": url,
                    "source": source,
                    "error": str(result),
                    "request_id": request_id,
                },
            )
        elif isinstance(result, list):
            all_articles.extend(result)

    if len(failed_feeds) == len(RSS_FEEDS):
        logger.error(
            "All feeds failed",
            extra={"failed_count": len(failed_feeds), "request_id": request_id},
        )
        return []

    logger.info(
        "Finished fetching all feeds",
        extra={
            "total_articles": len(all_articles),
            "failed_feeds": len(failed_feeds),
            "request_id": request_id,
        },
    )
    return all_articles


async def _fetch_feed_wrapper(
    url: str,
    source: str,
    region: str,
    lookback_hours: int,
    logger: Any,
    request_id: str,
) -> list[RawArticle]:
    """Wrapper для fetch_single_feed без создания нового request_id."""
    settings = get_settings()
    timeout_seconds = getattr(settings, "FETCH_TIMEOUT_SECONDS", 30.0)
    max_retries = getattr(settings, "FETCH_MAX_RETRIES", 3)
    base_delay = 1.0

    last_exception: Exception | None = None

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                async with session.get(url, timeout=timeout) as response:
                    if response.status >= 500:
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message=f"Server error: {response.status}",
                        )

                    if response.status == 404:
                        logger.warning(
                            "Feed not found (404)",
                            extra={"url": url, "source": source, "request_id": request_id},
                        )
                        return []

                    response.raise_for_status()
                    xml_content = await response.text()

                    feed_data = await _parse_feed_async(xml_content)

                    if feed_data.bozo:
                        logger.warning(
                            "Malformed RSS feed",
                            extra={
                                "url": url,
                                "source": source,
                                "error": str(feed_data.bozo_exception),
                                "request_id": request_id,
                            },
                        )

                    from datetime import timedelta

                    cutoff_time = datetime.now(UTC) - timedelta(hours=lookback_hours)

                    articles: list[RawArticle] = []
                    for entry in feed_data.entries:
                        published_raw = entry.get("published") or entry.get("updated")
                        published_at = _parse_published_date(published_raw)

                        if published_at is None:
                            continue

                        if published_at < cutoff_time:
                            continue

                        content = ""
                        if hasattr(entry, "content") and entry.content:
                            content = entry.content[0].get("value", "")
                        elif hasattr(entry, "summary"):
                            content = entry.summary
                        elif hasattr(entry, "description"):
                            content = entry.description

                        article_url = entry.get("link", "")
                        if not article_url:
                            continue

                        title = entry.get("title", "")

                        article = RawArticle(
                            url=article_url,
                            title=title,
                            content=content,
                            source=source,
                            region=region,
                            published_at=published_at,
                        )
                        articles.append(article)

                    logger.info(
                        f"Successfully fetched {len(articles)} articles from {source}",
                        extra={"url": url, "source": source, "request_id": request_id},
                    )
                    return articles

        except (TimeoutError, aiohttp.ClientError) as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"Retry {attempt + 1}/{max_retries} after {delay}s",
                    extra={
                        "url": url,
                        "source": source,
                        "error": str(e),
                        "attempt": attempt + 1,
                        "request_id": request_id,
                    },
                )
                await asyncio.sleep(delay)
            else:
                break

    logger.warning(
        "All retries exhausted for feed",
        extra={
            "url": url,
            "source": source,
            "error": str(last_exception) if last_exception else "Unknown error",
            "request_id": request_id,
        },
    )
    raise FeedFetchError(
        f"Failed to fetch feed {url} after {max_retries} retries: {last_exception}"
    )

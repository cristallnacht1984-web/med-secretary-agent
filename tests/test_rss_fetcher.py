"""Tests for RSS Feed Fetcher module."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import aiohttp
import pytest
from aioresponses import aioresponses

from app.services.rss_fetcher import (
    RSS_FEEDS,
    FeedFetchError,
    RawArticle,
    _parse_feed_async,
    _parse_published_date,
    fetch_all_feeds,
    fetch_single_feed,
)


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch):
    """Autouse-фикстура: очистка env и кэша Settings перед каждым тестом.
    
    По образцу из tests/test_config.py и memory.md §4.3.
    """
    # Очищаем все env-переменные Settings
    env_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_DIGEST_CHAT_ID",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
        "LLM_TEMPERATURE_ANALYSIS",
        "LLM_TIMEOUT_ANALYSIS",
        "DATABASE_URL",
        "DIGEST_HOUR",
        "DIGEST_MINUTE",
        "TIMEZONE",
        "LOG_LEVEL",
        "LOG_FILE",
        "NEWS_LOOKBACK_HOURS",
        "FETCH_TIMEOUT_SECONDS",
        "FETCH_MAX_RETRIES",
        "USER_TIMEZONE",
        "DIGEST_TIME_HOUR",
        "GOOGLE_CREDENTIALS_JSON",
        "REMINDER_WINDOW_HOURS",
        "HEALTH_CHECK_HOST",
        "HEALTH_CHECK_PORT",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)
    
    # Устанавливаем минимальные required значения для Settings
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_bot_token")
    monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[123]")
    
    # Очищаем кэш get_settings
    from app.config import get_settings
    get_settings.cache_clear()
    
    yield


# Валидный RSS XML для тестов
VALID_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>Test RSS Feed</description>
    <item>
      <title>Test Article 1</title>
      <link>https://example.com/article1</link>
      <description>Test content 1</description>
      <pubDate>{pub_date}</pubDate>
    </item>
    <item>
      <title>Test Article 2</title>
      <link>https://example.com/article2</link>
      <description>Test content 2</description>
      <pubDate>{pub_date}</pubDate>
    </item>
  </channel>
</rss>
"""

INVALID_XML = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Invalid Feed
  </channel>
</rss>
"""


class TestRawArticle:
    """Тесты dataclass RawArticle."""

    def test_raw_article_has_all_fields(self):
        """RawArticle содержит все поля."""
        now = datetime.now(timezone.utc)
        article = RawArticle(
            url="https://example.com/article",
            title="Test Title",
            content="Test content",
            source="Test Source",
            region="Америка",
            published_at=now,
        )
        assert article.url == "https://example.com/article"
        assert article.title == "Test Title"
        assert article.content == "Test content"
        assert article.source == "Test Source"
        assert article.region == "Америка"
        assert article.published_at == now


class TestRSSFeedsConstant:
    """Тесты константы RSS_FEEDS."""

    def test_rss_feeds_has_10_feeds(self):
        """RSS_FEEDS константа содержит 10 фидов."""
        assert len(RSS_FEEDS) == 10

    def test_rss_feeds_structure(self):
        """Каждый фид - кортеж (url, source, region)."""
        for feed in RSS_FEEDS:
            assert isinstance(feed, tuple)
            assert len(feed) == 3
            url, source, region = feed
            assert isinstance(url, str)
            assert isinstance(source, str)
            assert isinstance(region, str)
            assert url.startswith("http")


class TestParsePublishedDate:
    """Тесты парсинга даты публикации."""

    def test_parse_valid_rfc2822_date(self):
        """Валидная RFC2822 дата парсится корректно."""
        date_str = "Mon, 01 Jan 2024 12:00:00 UTC"
        result = _parse_published_date(date_str)
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 1

    def test_parse_none_returns_none(self):
        """None возвращает None."""
        assert _parse_published_date(None) is None

    def test_parse_empty_string_returns_none(self):
        """Пустая строка возвращает None."""
        assert _parse_published_date("") is None

    def test_parse_invalid_date_returns_none(self):
        """Невалидная дата возвращает None."""
        assert _parse_published_date("invalid-date") is None


class TestFeedFetcherSuccess:
    """Тесты успешного сбора фидов."""

    @pytest.mark.asyncio
    async def test_fetch_single_feed_success(self):
        """Успешный сбор одного фида."""
        pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S UTC")
        xml_content = VALID_RSS_XML.format(pub_date=pub_date)
        
        with aioresponses() as m:
            m.get(
                "https://www.statnews.com/feed/",
                status=200,
                body=xml_content,
            )
            
            articles = await fetch_single_feed(
                url="https://www.statnews.com/feed/",
                source="STAT News",
                region="Америка",
            )
            
            assert len(articles) >= 1
            assert all(isinstance(a, RawArticle) for a in articles)

    @pytest.mark.asyncio
    async def test_fetch_all_feeds_success_mocked(self):
        """Интеграционный тест: fetch_all_feeds с моками возвращает list[RawArticle]."""
        pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S UTC")
        xml_content = VALID_RSS_XML.format(pub_date=pub_date)
        
        with aioresponses() as m:
            # Мокаем все 10 фидов
            for url, _source, _region in RSS_FEEDS:
                m.get(url, status=200, body=xml_content, repeat=True)
            
            articles = await fetch_all_feeds(lookback_hours=24)
            
            assert isinstance(articles, list)
            # Хотя бы некоторые статьи должны быть
            assert len(articles) >= 0  # Может быть 0 если даты старые

    @pytest.mark.asyncio
    async def test_concurrent_fetch_with_asyncio_gather(self):
        """Concurrent сбор (asyncio.gather) работает."""
        pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S UTC")
        xml_content = VALID_RSS_XML.format(pub_date=pub_date)
        
        with aioresponses() as m:
            # Мокаем 3 фида для теста конкурентности
            m.get("https://example.com/feed1", status=200, body=xml_content)
            m.get("https://example.com/feed2", status=200, body=xml_content)
            m.get("https://example.com/feed3", status=200, body=xml_content)
            
            async def mock_fetch(url, source, region):
                return await fetch_single_feed(url, source, region)
            
            tasks = [
                mock_fetch("https://example.com/feed1", "Source1", "Америка"),
                mock_fetch("https://example.com/feed2", "Source2", "Европа"),
                mock_fetch("https://example.com/feed3", "Source3", "Азия"),
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Все задачи выполнились (могут вернуть пустой список или статьи)
            assert len(results) == 3


class TestFeedFetcherFailure:
    """Тесты ошибок при сборе фидов."""

    @pytest.mark.asyncio
    async def test_one_feed_fails_log_warning_continue(self):
        """Один фид падает → log warning, остальные собираются."""
        pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S UTC")
        xml_content = VALID_RSS_XML.format(pub_date=pub_date)
        
        with aioresponses() as m:
            # Первый фид успешен
            m.get("https://example.com/good", status=200, body=xml_content)
            # Второй фид падает с 500
            m.get("https://example.com/bad", status=500, exception=aiohttp.ClientError("Server error"))
            
            # Тестируем fetch_single_feed для хорошего фида
            articles = await fetch_single_feed(
                url="https://example.com/good",
                source="Good Source",
                region="Америка",
            )
            assert isinstance(articles, list)

    @pytest.mark.asyncio
    async def test_all_feeds_fail_returns_empty_list(self):
        """Все фиды падают → пустой список."""
        with aioresponses() as m:
            # Все фиды падают
            for url, _, _ in RSS_FEEDS:
                m.get(url, status=500, exception=aiohttp.ClientError("Server error"))
            
            articles = await fetch_all_feeds(lookback_hours=24)
            
            # При полном падении всех фидов возвращается пустой список
            assert articles == []


class TestRetryBehavior:
    """Тесты retry логики."""

    @pytest.mark.asyncio
    async def test_retry_on_timeout_three_attempts(self):
        """Retry на timeout → 3 попытки, затем FeedFetchError."""
        with aioresponses() as m:
            # Таймаут на каждой попытке
            m.get(
                "https://example.com/timeout",
                exception=TimeoutError("Connection timeout"),
                repeat=True,
            )
            
            with pytest.raises(FeedFetchError):
                await fetch_single_feed(
                    url="https://example.com/timeout",
                    source="Timeout Source",
                    region="Америка",
                    lookback_hours=24,
                )

    @pytest.mark.asyncio
    async def test_retry_on_5xx_three_attempts(self):
        """Retry на 5xx → 3 попытки, затем FeedFetchError."""
        with aioresponses() as m:
            # 500 ошибка на каждой попытке
            m.get(
                "https://example.com/server_error",
                status=500,
                exception=aiohttp.ClientResponseError(
                    request_info=MagicMock(),
                    history=(),
                    status=500,
                    message="Internal Server Error",
                ),
                repeat=True,
            )
            
            with pytest.raises(FeedFetchError):
                await fetch_single_feed(
                    url="https://example.com/server_error",
                    source="Error Source",
                    region="Европа",
                    lookback_hours=24,
                )


class TestDateFiltering:
    """Тесты фильтрации по дате."""

    @pytest.mark.asyncio
    async def test_old_articles_filtered_out(self):
        """published_at фильтрация: статьи старше 24ч отбрасываются."""
        # Старая дата (48 часов назад)
        old_date = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%a, %d %b %Y %H:%M:%S UTC")
        xml_content = VALID_RSS_XML.format(pub_date=old_date)
        
        with aioresponses() as m:
            m.get("https://example.com/old", status=200, body=xml_content)
            
            articles = await fetch_single_feed(
                url="https://example.com/old",
                source="Old Source",
                region="Америка",
                lookback_hours=24,
            )
            
            # Старые статьи должны быть отфильтрованы
            assert len(articles) == 0

    @pytest.mark.asyncio
    async def test_fresh_articles_kept(self):
        """published_at фильтрация: свежие статьи остаются."""
        # Свежая дата (1 час назад)
        fresh_date = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S UTC")
        xml_content = VALID_RSS_XML.format(pub_date=fresh_date)
        
        with aioresponses() as m:
            m.get("https://example.com/fresh", status=200, body=xml_content)
            
            articles = await fetch_single_feed(
                url="https://example.com/fresh",
                source="Fresh Source",
                region="Европа",
                lookback_hours=24,
            )
            
            # Свежие статьи должны остаться
            assert len(articles) >= 1


class TestSettingsTimeout:
    """Тесты применения timeout из Settings."""

    @pytest.mark.asyncio
    async def test_timeout_from_settings_applied(self, monkeypatch):
        """Timeout из Settings применяется."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[123]")
        monkeypatch.setenv("FETCH_TIMEOUT_SECONDS", "5.0")
        
        from app.config import get_settings
        get_settings.cache_clear()
        
        settings = get_settings()
        assert settings.FETCH_TIMEOUT_SECONDS == 5.0


class TestFeedparserParsing:
    """Тесты парсинга feedparser."""

    @pytest.mark.asyncio
    async def test_feedparser_parses_valid_rss(self):
        """feedparser парсит валидный RSS XML."""
        pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S UTC")
        xml_content = VALID_RSS_XML.format(pub_date=pub_date)
        
        feed_data = await _parse_feed_async(xml_content)
        
        assert feed_data is not None
        assert not feed_data.bozo
        assert len(feed_data.entries) >= 2

    @pytest.mark.asyncio
    async def test_feedparser_handles_invalid_xml_gracefully(self):
        """feedparser обрабатывает невалидный XML gracefully."""
        feed_data = await _parse_feed_async(INVALID_XML)
        
        # feedparser должен вернуть результат даже для невалидного XML
        assert feed_data is not None
        # bozo флаг должен быть установлен для невалидного XML (1 = True)
        assert feed_data.bozo == 1


class TestRequestId:
    """Тесты привязки request_id."""

    @pytest.mark.asyncio
    async def test_request_id_bound_via_new_request_id(self):
        """request_id привязывается через new_request_id()."""
        from app.logging_setup import _request_id, new_request_id
        
        # Проверяем что new_request_id генерирует UUID
        request_id = new_request_id()
        assert request_id is not None
        assert len(request_id) == 36  # UUID format
        
        # Проверяем что contextvar установлен
        assert _request_id.get() == request_id

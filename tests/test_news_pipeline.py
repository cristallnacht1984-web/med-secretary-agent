"""Tests for News Pipeline Service.

Tests deduplication and batching functionality with mocked repository.
No real database connections - uses AsyncMock for repository methods.
"""
import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.config import get_settings
from app.services.news_pipeline import (
    _compute_title_hash,
    build_batches,
    deduplicate_articles,
    prepare_batches_for_analysis,
)
from app.services.rss_fetcher import RawArticle


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch):
    """Clean environment variables and clear settings cache between tests.

    Prevents shell environment from affecting test results.
    See memory.md §4.3 for details.
    """
    # Set required env vars with dummy values to pass validation
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy_token")
    monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[123456789]")

    # Remove all other Settings-related env variables
    env_vars = [
        "TELEGRAM_ADMIN_ID",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
        "LLM_MAX_TOKENS",
        "LLM_TIMEOUT_ANALYSIS",
        "LLM_TIMEOUT_CLASSIFICATION",
        "LLM_TIMEOUT_REMINDER",
        "LLM_TEMPERATURE_ANALYSIS",
        "LLM_TEMPERATURE_CLASSIFICATION",
        "LLM_TEMPERATURE_REMINDER",
        "LLM_RATE_LIMIT_RPM",
        "LLM_RATE_LIMIT_TPM",
        "LLM_MAX_RETRIES",
        "DATABASE_URL",
        "GOOGLE_CREDENTIALS_FILE",
        "GOOGLE_TOKEN_FILE",
        "GOOGLE_CALENDAR_ID",
        "GOOGLE_CREDENTIALS_JSON",
        "DIGEST_HOUR",
        "DIGEST_MINUTE",
        "DIGEST_TIME_HOUR",
        "REMINDER_POLL_INTERVAL_MINUTES",
        "REMINDER_LOOKAHEAD_MINUTES",
        "REMINDER_WINDOW_HOURS",
        "HEALTH_CHECK_HOST",
        "HEALTH_CHECK_PORT",
        "TIMEZONE",
        "USER_TIMEZONE",
        "LOG_LEVEL",
        "LOG_FILE",
        "NEWS_LOOKBACK_HOURS",
        "NEWS_DEDUP_WINDOW_DAYS",
        "NEWS_BATCH_MIN",
        "NEWS_BATCH_MAX",
        "NEWS_DELIVERY_RETRIES",
        "NEWS_DELIVERY_RETRY_DELAY_MINUTES",
        "FETCH_TIMEOUT_SECONDS",
        "FETCH_MAX_RETRIES",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)

    # Clear settings cache
    get_settings.cache_clear()


def _make_article(url: str, title: str, source: str = "TestSource") -> RawArticle:
    """Helper to create a RawArticle for testing."""
    return RawArticle(
        url=url,
        title=title,
        content="Test content",
        source=source,
        region="TestRegion",
        published_at=datetime.now(timezone.utc),
    )


class TestComputeTitleHash:
    """Tests for _compute_title_hash helper function."""

    def test_hash_is_md5_hex(self):
        """Hash should be valid MD5 hex string."""
        title = "Test Title"
        result = _compute_title_hash(title)
        assert len(result) == 32  # MD5 produces 32 hex characters
        assert all(c in "0123456789abcdef" for c in result)

    def test_same_title_same_hash(self):
        """Same title should produce same hash."""
        title = "Identical Title"
        hash1 = _compute_title_hash(title)
        hash2 = _compute_title_hash(title)
        assert hash1 == hash2

    def test_different_titles_different_hashes(self):
        """Different titles should produce different hashes."""
        hash1 = _compute_title_hash("Title A")
        hash2 = _compute_title_hash("Title B")
        assert hash1 != hash2


class TestDeduplicateArticles:
    """Tests for deduplicate_articles function."""

    @pytest.mark.asyncio
    async def test_all_unique_articles_returned(self):
        """When no duplicates exist, all articles should be returned."""
        articles = [
            _make_article("http://a.com", "Title A"),
            _make_article("http://b.com", "Title B"),
            _make_article("http://c.com", "Title C"),
        ]

        # Mock repository to return False (no duplicates)
        mock_repo = AsyncMock()
        mock_repo.is_article_duplicate = AsyncMock(return_value=False)
        mock_repo.add_article = AsyncMock()

        with patch("app.services.news_pipeline.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.services.news_pipeline.Repository", return_value=mock_repo):
                result = await deduplicate_articles(articles)

        assert len(result) == 3
        assert result == articles
        # add_article should be called for each article
        assert mock_repo.add_article.call_count == 3

    @pytest.mark.asyncio
    async def test_duplicates_filtered_out(self):
        """Duplicate articles should be filtered out."""
        articles = [
            _make_article("http://a.com", "Title A"),
            _make_article("http://b.com", "Title B"),  # Will be marked as duplicate
            _make_article("http://c.com", "Title C"),
            _make_article("http://d.com", "Title D"),  # Will be marked as duplicate
            _make_article("http://e.com", "Title E"),  # Will be marked as duplicate
        ]

        # Mock repository: articles at index 1, 3, 4 are duplicates
        mock_repo = AsyncMock()
        duplicate_indices = {1, 3, 4}

        async def is_dup_side_effect(url, title_hash):
            # Check if this article should be a duplicate based on URL
            for i, art in enumerate(articles):
                if art.url == url:
                    return i in duplicate_indices
            return False

        mock_repo.is_article_duplicate = AsyncMock(side_effect=is_dup_side_effect)
        mock_repo.add_article = AsyncMock()

        with patch("app.services.news_pipeline.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.services.news_pipeline.Repository", return_value=mock_repo):
                result = await deduplicate_articles(articles)

        # Only non-duplicates should be returned (indices 0, 2)
        assert len(result) == 2
        assert result[0].url == "http://a.com"
        assert result[1].url == "http://c.com"

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        """Empty input list should return empty list."""
        result = await deduplicate_articles([])
        assert result == []

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_list(self):
        """Database error should return empty list (graceful degradation)."""
        articles = [_make_article("http://a.com", "Title A")]

        with patch("app.services.news_pipeline.get_session") as mock_get_session:
            # Simulate database error
            mock_get_session.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB error"))
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await deduplicate_articles(articles)

        assert result == []

    @pytest.mark.asyncio
    async def test_title_hash_computed_correctly(self):
        """Verify title hash is computed using MD5."""
        article = _make_article("http://a.com", "Test Title")
        expected_hash = hashlib.md5(b"Test Title").hexdigest()

        mock_repo = AsyncMock()
        mock_repo.is_article_duplicate = AsyncMock(return_value=False)
        mock_repo.add_article = AsyncMock()

        with patch("app.services.news_pipeline.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.services.news_pipeline.Repository", return_value=mock_repo):
                await deduplicate_articles([article])

        # Verify add_article was called with correct title_hash
        mock_repo.add_article.assert_called_once()
        call_args = mock_repo.add_article.call_args
        assert call_args.kwargs["title_hash"] == expected_hash


class TestBuildBatches:
    """Tests for build_batches function."""

    def test_10_articles_produces_5_5(self):
        """10 articles should produce batches of [5, 5]."""
        articles = [_make_article(f"http://{i}.com", f"Title {i}") for i in range(10)]
        batches = build_batches(articles)

        assert len(batches) == 2
        assert len(batches[0]) == 5
        assert len(batches[1]) == 5

    def test_7_articles_produces_5_2(self):
        """7 articles should produce batches of [5, 2]."""
        articles = [_make_article(f"http://{i}.com", f"Title {i}") for i in range(7)]
        batches = build_batches(articles)

        assert len(batches) == 2
        assert len(batches[0]) == 5
        assert len(batches[1]) == 2

    def test_2_articles_less_than_min_single_batch(self):
        """2 articles (< NEWS_BATCH_MIN=3) should produce single batch."""
        articles = [_make_article(f"http://{i}.com", f"Title {i}") for i in range(2)]
        batches = build_batches(articles)

        assert len(batches) == 1
        assert len(batches[0]) == 2

    def test_empty_input_returns_empty(self):
        """Empty input should return empty list."""
        batches = build_batches([])
        assert batches == []

    def test_exactly_batch_min_articles(self):
        """Exactly NEWS_BATCH_MIN articles should produce single batch."""
        # NEWS_BATCH_MIN = 3 by default
        articles = [_make_article(f"http://{i}.com", f"Title {i}") for i in range(3)]
        batches = build_batches(articles)

        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_exactly_batch_max_articles(self):
        """Exactly NEWS_BATCH_MAX articles should produce single batch."""
        # NEWS_BATCH_MAX = 5 by default
        articles = [_make_article(f"http://{i}.com", f"Title {i}") for i in range(5)]
        batches = build_batches(articles)

        assert len(batches) == 1
        assert len(batches[0]) == 5

    def test_12_articles_produces_5_5_2(self):
        """12 articles should produce batches of [5, 5, 2]."""
        articles = [_make_article(f"http://{i}.com", f"Title {i}") for i in range(12)]
        batches = build_batches(articles)

        assert len(batches) == 3
        assert len(batches[0]) == 5
        assert len(batches[1]) == 5
        assert len(batches[2]) == 2


class TestPrepareBatchesForAnalysis:
    """Tests for prepare_batches_for_analysis function."""

    @pytest.mark.asyncio
    async def test_full_pipeline_works(self):
        """Full pipeline should fetch, deduplicate, batch, and convert to dict."""
        # Mock RSS fetcher to return some articles
        mock_articles = [
            _make_article("http://a.com", "Title A", "SourceA"),
            _make_article("http://b.com", "Title B", "SourceB"),
            _make_article("http://c.com", "Title C", "SourceC"),
            _make_article("http://d.com", "Title D", "SourceD"),
            _make_article("http://e.com", "Title E", "SourceE"),
            _make_article("http://f.com", "Title F", "SourceF"),
        ]

        # Mock deduplicate to return all (no duplicates)
        async def mock_dedup(articles):
            return articles

        with patch("app.services.news_pipeline.fetch_all_feeds", return_value=mock_articles):
            with patch("app.services.news_pipeline.deduplicate_articles", side_effect=mock_dedup):
                result = await prepare_batches_for_analysis(lookback_hours=24)

        # Should have batches with dict format
        assert isinstance(result, list)
        # Verify structure: list[list[dict]]
        if result:
            assert isinstance(result[0], list)
            if result[0]:
                assert isinstance(result[0][0], dict)

    @pytest.mark.asyncio
    async def test_dict_format_has_required_keys(self):
        """Each article dict should have url, title, content, source keys."""
        mock_articles = [
            _make_article("http://test.com", "Test Title", "TestSource"),
        ]
        mock_articles[0].content = "Test content here"

        async def mock_dedup(articles):
            return articles

        with patch("app.services.news_pipeline.fetch_all_feeds", return_value=mock_articles):
            with patch("app.services.news_pipeline.deduplicate_articles", side_effect=mock_dedup):
                with patch("app.services.news_pipeline.build_batches", return_value=[[mock_articles[0]]]):
                    result = await prepare_batches_for_analysis()

        assert len(result) > 0
        article_dict = result[0][0]
        assert "url" in article_dict
        assert "title" in article_dict
        assert "content" in article_dict
        assert "source" in article_dict
        assert article_dict["url"] == "http://test.com"
        assert article_dict["title"] == "Test Title"
        assert article_dict["source"] == "TestSource"

    @pytest.mark.asyncio
    async def test_no_articles_fetched_returns_empty(self):
        """Empty RSS fetch should return empty result."""
        with patch("app.services.news_pipeline.fetch_all_feeds", return_value=[]):
            result = await prepare_batches_for_analysis()

        assert result == []

    @pytest.mark.asyncio
    async def test_no_unique_articles_returns_empty(self):
        """All duplicates should return empty result."""
        mock_articles = [_make_article("http://a.com", "Title A")]

        async def mock_dedup(articles):
            return []  # All filtered as duplicates

        with patch("app.services.news_pipeline.fetch_all_feeds", return_value=mock_articles):
            with patch("app.services.news_pipeline.deduplicate_articles", side_effect=mock_dedup):
                result = await prepare_batches_for_analysis()

        assert result == []

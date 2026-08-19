"""Tests for LLM client module."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from openai import APIStatusError, APITimeoutError
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.llm.client import LLMClient, RateLimiter
from app.llm.schemas import (
    IntentClassification,
    NewsAnalysisBatch,
    ReminderSummary,
)


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch: pytest.MonkeyPatch):
    """Clean environment variables and clear settings cache before each test."""
    env_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_DIGEST_CHAT_ID",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
        "LLM_TEMPERATURE_ANALYSIS",
        "LLM_TEMPERATURE_CLASSIFICATION",
        "LLM_TEMPERATURE_REMINDER",
        "LLM_MAX_TOKENS",
        "LLM_TIMEOUT_ANALYSIS",
        "LLM_TIMEOUT_CLASSIFICATION",
        "LLM_TIMEOUT_REMINDER",
        "LLM_RATE_LIMIT_RPM",
        "LLM_RATE_LIMIT_TPM",
        "LLM_MAX_RETRIES",
        "DATABASE_URL",
        "GOOGLE_CREDENTIALS_JSON",
        "GOOGLE_CREDENTIALS_FILE",
        "GOOGLE_TOKEN_FILE",
        "GOOGLE_CALENDAR_ID",
        "DIGEST_TIME_HOUR",
        "DIGEST_HOUR",
        "DIGEST_MINUTE",
        "REMINDER_POLL_INTERVAL_MINUTES",
        "REMINDER_WINDOW_HOURS",
        "REMINDER_LOOKAHEAD_MINUTES",
        "HEALTH_CHECK_HOST",
        "HEALTH_CHECK_PORT",
        "USER_TIMEZONE",
        "TIMEZONE",
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

    # Set required values
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_bot_token")
    monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123456789")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[111, 222]")

    # Clear the lru_cache to ensure fresh settings
    get_settings.cache_clear()

    yield

    # Cleanup after test
    get_settings.cache_clear()


@pytest.fixture
def mock_openai_client():
    """Create a mock OpenAI client."""
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock()
    mock_client.close = AsyncMock()
    return mock_client


@pytest.fixture
def valid_news_batch_response():
    """Valid JSON response for news analysis."""
    return {
        "articles": [
            {
                "article_url": "https://example.com/article1",
                "region": "Америка",
                "source": "MedicalNews",
                "essence": "New treatment discovered",
                "significance": "High",
                "scientific_summary_ru": "Новое лечение найдено",
            },
            {
                "article_url": "https://example.com/article2",
                "region": "Европа",
                "source": "EuroMed",
                "essence": "Clinical trial results",
                "significance": "Medium",
                "scientific_summary_ru": "Результаты испытаний",
            },
            {
                "article_url": "https://example.com/article3",
                "region": "Россия",
                "source": "RusMed",
                "essence": "Vaccine development",
                "significance": "Low",
                "scientific_summary_ru": "Разработка вакцины",
            },
        ]
    }


@pytest.fixture
def valid_intent_response():
    """Valid JSON response for intent classification."""
    return {
        "intent": "create_event",
        "confidence": 0.95,
        "parameters": {"title": "Meeting", "date": "2024-01-15"},
    }


@pytest.fixture
def valid_reminder_response():
    """Valid JSON response for reminder summary."""
    return {
        "event_title": "Doctor Appointment",
        "event_start": "2024-01-15T10:00:00",
        "summary": "Visit doctor for checkup",
        "preparation_tips": ["Bring medical records", "Arrive 15 min early"],
    }


class TestLLMClientInit:
    """Test LLMClient initialization."""

    def test_init_with_default_settings(self, monkeypatch):
        """Test client initializes with default settings."""
        monkeypatch.setenv("LLM_BASE_URL", "http://test.local/v1")
        monkeypatch.setenv("LLM_API_KEY", "test_key")
        monkeypatch.setenv("LLM_MODEL_NAME", "test_model")

        client = LLMClient()
        assert client._settings.LLM_BASE_URL == "http://test.local/v1"
        assert client._settings.LLM_API_KEY.get_secret_value() == "test_key"
        assert client._model == "test_model"

    def test_init_with_custom_settings(self):
        """Test client initializes with custom settings."""
        settings = Settings(
            TELEGRAM_BOT_TOKEN="token",
            TELEGRAM_DIGEST_CHAT_ID="-1001234567890",
            LLM_BASE_URL="http://custom.local/v1",
            LLM_API_KEY="custom_key",
            LLM_MODEL_NAME="custom_model",
        )
        client = LLMClient(settings=settings)
        assert client._settings.LLM_BASE_URL == "http://custom.local/v1"
        assert client._model == "custom_model"


class TestAnalyzeNewsBatch:
    """Test analyze_news_batch method."""

    @pytest.mark.asyncio
    async def test_successful_analysis(
        self, mock_openai_client, valid_news_batch_response
    ):
        """Test successful news batch analysis."""
        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 200
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps(valid_news_batch_response)))
        ]
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            articles = [
                {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
            ]
            result = await client.analyze_news_batch(articles)

            assert isinstance(result, NewsAnalysisBatch)
            assert len(result.articles) == 3
            mock_openai_client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_json_raises_validation_error(
        self, mock_openai_client
    ):
        """Test that invalid JSON from LLM raises ValidationError."""
        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 50
        # Invalid JSON - missing required fields
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"invalid": "data"}'))
        ]
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            articles = [
                {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
            ]

            with pytest.raises(ValidationError):
                await client.analyze_news_batch(articles)


class TestClassifyIntent:
    """Test classify_intent method."""

    @pytest.mark.asyncio
    async def test_successful_classification(
        self, mock_openai_client, valid_intent_response
    ):
        """Test successful intent classification."""
        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 30
        mock_response.usage.completion_tokens = 50
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps(valid_intent_response)))
        ]
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            result = await client.classify_intent("Schedule a meeting tomorrow")

            assert isinstance(result, IntentClassification)
            assert result.intent == "create_event"
            assert result.confidence == 0.95


class TestSummarizeReminder:
    """Test summarize_reminder method."""

    @pytest.mark.asyncio
    async def test_successful_summary(
        self, mock_openai_client, valid_reminder_response
    ):
        """Test successful reminder summarization."""
        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 40
        mock_response.usage.completion_tokens = 60
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps(valid_reminder_response)))
        ]
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            event = {
                "title": "Doctor Appointment",
                "start_time": "2024-01-15T10:00:00",
                "description": "Annual checkup",
                "location": "Hospital",
            }
            result = await client.summarize_reminder(event)

            assert isinstance(result, ReminderSummary)
            assert result.event_title == "Doctor Appointment"


class TestRetryBehavior:
    """Test retry behavior with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_on_timeout_then_success(
        self, mock_openai_client, valid_news_batch_response
    ):
        """Test retry occurs on APITimeoutError then succeeds."""
        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 200
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps(valid_news_batch_response)))
        ]

        # First call raises timeout, second succeeds
        mock_openai_client.chat.completions.create.side_effect = [
            APITimeoutError(request=httpx.Request("POST", "http://test.com")),
            mock_response,
        ]

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            articles = [
                {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
            ]
            result = await client.analyze_news_batch(articles)

            assert isinstance(result, NewsAnalysisBatch)
            assert mock_openai_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_5xx_error_then_success(
        self, mock_openai_client, valid_news_batch_response
    ):
        """Test retry occurs on APIStatusError 5xx then succeeds."""
        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 200
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps(valid_news_batch_response)))
        ]

        # First call raises 5xx error, second succeeds
        mock_openai_client.chat.completions.create.side_effect = [
            APIStatusError(
                "Internal Server Error",
                response=MagicMock(status_code=500),
                body=None,
            ),
            mock_response,
        ]

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            articles = [
                {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
            ]
            result = await client.analyze_news_batch(articles)

            assert isinstance(result, NewsAnalysisBatch)
            assert mock_openai_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises_exception(
        self, mock_openai_client
    ):
        """Test that exceeding max retries raises exception."""
        # All calls raise timeout
        mock_openai_client.chat.completions.create.side_effect = [
            APITimeoutError(request=httpx.Request("POST", "http://test.com")),
            APITimeoutError(request=httpx.Request("POST", "http://test.com")),
            APITimeoutError(request=httpx.Request("POST", "http://test.com")),
            APITimeoutError(request=httpx.Request("POST", "http://test.com")),
        ]

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            articles = [
                {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
            ]

            with pytest.raises(APITimeoutError):
                await client.analyze_news_batch(articles)

            # Should have tried 4 times (max_retries=3 means 4 attempts total)
            assert mock_openai_client.chat.completions.create.call_count == 4


class TestRateLimiter:
    """Test rate limiter functionality."""

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_under_limit(self):
        """Test rate limiter allows requests under limit."""
        limiter = RateLimiter(rpm=10, tpm=1000)
        # Should not block
        await limiter.acquire(100)

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_over_rpm(self):
        """Test rate limiter blocks when RPM exceeded."""
        limiter = RateLimiter(rpm=2, tpm=10000)

        # Make 2 requests
        await limiter.acquire(0)
        await limiter.acquire(0)

        # Third request should wait (we'll use short timeout for test)
        start = asyncio.get_event_loop().time()
        try:
            await asyncio.wait_for(limiter.acquire(0), timeout=0.5)
        except TimeoutError:
            pass  # Expected - rate limit kicked in
        end = asyncio.get_event_loop().time()

        # Should have waited some time
        assert end - start >= 0.4  # Allow some tolerance


class TestLogging:
    """Test logging behavior."""

    @pytest.mark.asyncio
    async def test_token_counts_logged(
        self, mock_openai_client, valid_news_batch_response
    ):
        """Test that prompt_tokens and completion_tokens are logged."""
        from unittest.mock import patch as mock_patch

        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 150
        mock_response.usage.completion_tokens = 250
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps(valid_news_batch_response)))
        ]
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            with mock_patch("app.llm.client.get_logger") as mock_get_logger:
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger
                
                client = LLMClient()
                articles = [
                    {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                    {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                    {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
                ]
                await client.analyze_news_batch(articles)
                
                # Проверяем, что логгер был вызван с token counts
                mock_logger.info.assert_called_once()
                call_kwargs = mock_logger.info.call_args[1]
                assert call_kwargs["prompt_tokens"] == 150
                assert call_kwargs["completion_tokens"] == 250
                assert "request_id" in call_kwargs

    @pytest.mark.asyncio
    async def test_api_key_not_logged(
        self, mock_openai_client, valid_news_batch_response, caplog
    ):
        """Test that api_key is NOT logged."""
        import logging

        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 50
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps(valid_news_batch_response)))
        ]
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            with caplog.at_level(logging.DEBUG):
                client = LLMClient()
                articles = [
                    {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                    {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                    {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
                ]
                await client.analyze_news_batch(articles)

                # Verify api_key not in logs
                for record in caplog.records:
                    assert "test_key" not in str(record.message)
                    assert "dummy" not in str(record.message)


class TestTimeoutSettings:
    """Test timeout settings are used correctly."""

    @pytest.mark.asyncio
    async def test_analysis_uses_120s_timeout(self, mock_openai_client, valid_news_batch_response, monkeypatch):
        """Test that analysis uses LLM_TIMEOUT_ANALYSIS (120s)."""
        monkeypatch.setenv("LLM_TIMEOUT_ANALYSIS", "120")
        get_settings.cache_clear()

        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 50
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps(valid_news_batch_response)))
        ]
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            articles = [
                {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
            ]
            await client.analyze_news_batch(articles)

            # Verify timeout was passed
            call_args = mock_openai_client.chat.completions.create.call_args
            assert call_args[1]["timeout"] == 120


class TestAclose:
    """Test aclose method."""

    @pytest.mark.asyncio
    async def test_aclose_closes_client(self, mock_openai_client):
        """Test that aclose closes the underlying client."""
        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            await client.aclose()

            mock_openai_client.close.assert_called_once()


class TestRateLimiterUnit:
    """Unit tests for RateLimiter class."""

    @pytest.mark.asyncio
    async def test_init(self):
        """Test RateLimiter initialization."""
        limiter = RateLimiter(rpm=60, tpm=100000)
        assert limiter.rpm == 60
        assert limiter.tpm == 100000

    @pytest.mark.asyncio
    async def test_acquire_empty(self):
        """Test acquire with empty history."""
        limiter = RateLimiter(rpm=10, tpm=1000)
        await limiter.acquire(100)
        assert len(limiter._requests) == 1

    @pytest.mark.asyncio
    async def test_acquire_tracks_tokens(self):
        """Test acquire tracks tokens."""
        limiter = RateLimiter(rpm=10, tpm=1000)
        await limiter.acquire(500)
        assert len(limiter._tokens) == 1
        assert limiter._tokens[0][1] == 500

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_over_tpm(self):
        """Test rate limiter blocks when TPM exceeded."""
        limiter = RateLimiter(rpm=100, tpm=200)

        # Make request using 150 tokens
        await limiter.acquire(150)

        # Next request of 100 tokens should wait (total would be 250 > 200)
        start = asyncio.get_event_loop().time()
        try:
            await asyncio.wait_for(limiter.acquire(100), timeout=0.5)
        except TimeoutError:
            pass  # Expected - rate limit kicked in
        end = asyncio.get_event_loop().time()

        # Should have waited some time
        assert end - start >= 0.4  # Allow some tolerance


class TestRetryBehaviorEdgeCases:
    """Test edge cases for retry behavior."""

    @pytest.mark.asyncio
    async def test_4xx_error_not_retried(self, mock_openai_client):
        """Test that 4xx errors are NOT retried (only 5xx)."""
        # All calls raise 4xx error
        mock_openai_client.chat.completions.create.side_effect = [
            APIStatusError(
                "Bad Request",
                response=MagicMock(status_code=400),
                body=None,
            ),
        ]

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            articles = [
                {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
            ]

            with pytest.raises(APIStatusError):
                await client.analyze_news_batch(articles)

            # Should have tried only once (4xx errors are not retried)
            assert mock_openai_client.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_connection_refused_retry_then_success(
        self, mock_openai_client, valid_news_batch_response
    ):
        """Test retry occurs on ConnectionRefusedError then succeeds."""
        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 200
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps(valid_news_batch_response)))
        ]

        # First call raises ConnectionRefusedError, second succeeds
        mock_openai_client.chat.completions.create.side_effect = [
            ConnectionRefusedError("Connection refused"),
            mock_response,
        ]

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            articles = [
                {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
            ]
            result = await client.analyze_news_batch(articles)

            assert isinstance(result, NewsAnalysisBatch)
            assert mock_openai_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_connection_refused(
        self, mock_openai_client
    ):
        """Test that exceeding max retries on ConnectionRefusedError raises exception."""
        # All calls raise ConnectionRefusedError
        mock_openai_client.chat.completions.create.side_effect = [
            ConnectionRefusedError("Connection refused"),
            ConnectionRefusedError("Connection refused"),
            ConnectionRefusedError("Connection refused"),
            ConnectionRefusedError("Connection refused"),
        ]

        with patch("app.llm.client.AsyncOpenAI", return_value=mock_openai_client):
            client = LLMClient()
            articles = [
                {"url": "https://a.com", "title": "A", "content": "Content A", "source": "SrcA"},
                {"url": "https://b.com", "title": "B", "content": "Content B", "source": "SrcB"},
                {"url": "https://c.com", "title": "C", "content": "Content C", "source": "SrcC"},
            ]

            with pytest.raises(ConnectionRefusedError):
                await client.analyze_news_batch(articles)

            # Should have tried 4 times (max_retries=3 means 4 attempts total)
            assert mock_openai_client.chat.completions.create.call_count == 4

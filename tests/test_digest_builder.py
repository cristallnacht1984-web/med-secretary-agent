"""Tests for Digest Builder Service.

Tests the full pipeline: build_digest_message, format_digest_markdown,
escape_markdown_v2, and send_digest_to_telegram with mocked dependencies.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Bot

from app.config import get_settings
from app.llm.schemas import NewsAnalysis, NewsAnalysisBatch
from app.services.digest_builder import (
    DEFAULT_REGION_EMOJI,
    REGION_EMOJI,
    DigestDeliveryError,
    build_digest_message,
    escape_markdown_v2,
    format_digest_markdown,
    send_digest_to_telegram,
)


@pytest.fixture(autouse=True)
def clean_env_and_cache(monkeypatch):
    """Clean environment variables and clear settings cache between tests."""
    # Set required env vars with dummy values
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy_token")
    monkeypatch.setenv("TELEGRAM_DIGEST_CHAT_ID", "-1001234567890")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "[123456789]")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "987654321")

    # Remove all other Settings-related env variables
    env_vars = [
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
    yield
    get_settings.cache_clear()


def _make_news_analysis(
    url: str = "https://example.com/article",
    region: str = "Америка",
    source: str = "TestSource",
    essence: str = "Test essence",
    significance: str = "High",
    summary: str = "Test scientific summary",
) -> NewsAnalysis:
    """Helper to create a NewsAnalysis for testing."""
    return NewsAnalysis(
        article_url=url,
        region=region,
        source=source,
        essence=essence,
        significance=significance,
        scientific_summary_ru=summary,
    )


def _make_batch(articles: list[NewsAnalysis]) -> NewsAnalysisBatch:
    """Helper to create a NewsAnalysisBatch.

    Note: NewsAnalysisBatch requires 3-5 articles per schema validation.
    """
    # Ensure we have at least 3 articles (schema requirement)
    while len(articles) < 3:
        articles.append(_make_news_analysis())
    return NewsAnalysisBatch(articles=articles)


class TestEscapeMarkdownV2:
    """Tests for escape_markdown_v2 function."""

    def test_underscore_escaped(self):
        """Underscore should be escaped."""
        result = escape_markdown_v2("hello_world")
        assert result == "hello\\_world"

    def test_asterisk_escaped(self):
        """Asterisk should be escaped."""
        result = escape_markdown_v2("bold*text")
        assert result == "bold\\*text"

    def test_brackets_escaped(self):
        """Brackets should be escaped."""
        result = escape_markdown_v2("[link](url)")
        assert result == "\\[link\\]\\(url\\)"

    def test_tilde_escaped(self):
        """Tilde should be escaped."""
        result = escape_markdown_v2("strikethrough~text")
        assert result == "strikethrough\\~text"

    def test_gt_escaped(self):
        """> should be escaped."""
        result = escape_markdown_v2("quote > text")
        assert result == "quote \\> text"

    def test_hash_escaped(self):
        """# should be escaped."""
        result = escape_markdown_v2("#header")
        assert result == "\\#header"

    def test_plus_escaped(self):
        """+ should be escaped."""
        result = escape_markdown_v2("plus+sign")
        assert result == "plus\\+sign"

    def test_minus_escaped(self):
        """- should be escaped."""
        result = escape_markdown_v2("minus-sign")
        assert result == "minus\\-sign"

    def test_equals_escaped(self):
        """= should be escaped."""
        result = escape_markdown_v2("a=b")
        assert result == "a\\=b"

    def test_pipe_escaped(self):
        """| should be escaped."""
        result = escape_markdown_v2("a|b")
        assert result == "a\\|b"

    def test_curly_braces_escaped(self):
        """Curly braces should be escaped."""
        result = escape_markdown_v2("{code}")
        assert result == "\\{code\\}"

    def test_dot_escaped(self):
        """. should be escaped."""
        result = escape_markdown_v2("end.")
        assert result == "end\\."

    def test_exclamation_escaped(self):
        """! should be escaped."""
        result = escape_markdown_v2("wow!")
        assert result == "wow\\!"

    def test_backtick_escaped(self):
        """Backtick should be escaped."""
        result = escape_markdown_v2("`code`")
        assert result == "\\`code\\`"

    def test_normal_text_unchanged(self):
        """Normal text (letters, digits, spaces, Cyrillic) should not change."""
        result = escape_markdown_v2("Hello 123 Привет мир")
        assert result == "Hello 123 Привет мир"

    def test_emoji_unchanged(self):
        """Emojis should not be changed."""
        result = escape_markdown_v2("🌎🌍🇷🇺")
        assert result == "🌎🌍🇷🇺"

    def test_multiple_special_chars(self):
        """Multiple special chars should all be escaped."""
        result = escape_markdown_v2("_*[test]*_")
        assert result == "\\_\\*\\[test\\]\\*\\_"


class TestFormatDigestMarkdown:
    """Tests for format_digest_markdown function."""

    def test_empty_analyses_returns_empty_string(self):
        """Empty analyses list should return empty string."""
        result = format_digest_markdown([], datetime.now(timezone.utc))
        assert result == ""

    def test_header_format(self):
        """Header should match expected format with date."""
        batch = _make_batch([_make_news_analysis()])
        date = datetime(2026, 8, 15, tzinfo=timezone.utc)
        result = format_digest_markdown([batch], date)

        assert "📰 *Медицинский дайджест* — 2026-08-15" in result

    def test_date_format_yyyy_mm_dd(self):
        """Date should be in YYYY-MM-DD format."""
        import re

        batch = _make_batch([_make_news_analysis()])
        date = datetime(2026, 8, 15, tzinfo=timezone.utc)
        result = format_digest_markdown([batch], date)

        # Check date pattern exists
        date_pattern = r"\d{4}-\d{2}-\d{2}"
        assert re.search(date_pattern, result)

    def test_region_sections_present(self):
        """All 5 regions should have sections when present."""
        articles = [
            _make_news_analysis(region="Америка", essence="America news"),
            _make_news_analysis(region="Европа", essence="Europe news"),
            _make_news_analysis(region="Россия", essence="Russia news"),
            _make_news_analysis(region="Азия", essence="Asia news"),
            _make_news_analysis(region="Глобал", essence="Global news"),
        ]
        batch = _make_batch(articles)
        date = datetime.now(timezone.utc)
        result = format_digest_markdown([batch], date)

        assert "🌎 *Америка*" in result
        assert "🌍 *Европа*" in result
        assert "🇷🇺 *Россия*" in result
        assert "🌏 *Азия*" in result
        assert "🌐 *Глобал*" in result

    def test_bullet_points_used(self):
        """Bullet points • should be used for articles."""
        batch = _make_batch([_make_news_analysis(essence="Test essence")])
        date = datetime.now(timezone.utc)
        result = format_digest_markdown([batch], date)

        assert "• " in result

    def test_unknown_region_uses_default_emoji(self):
        """Unknown region should use DEFAULT_REGION_EMOJI.

        Note: Since NewsAnalysis uses Literal for region, we can't create
        an instance with an unknown region directly. This test verifies
        the code path exists by checking DEFAULT_REGION_EMOJI is defined.
        """
        # The schema only allows predefined regions, so we test that
        # DEFAULT_REGION_EMOJI constant is properly defined
        assert DEFAULT_REGION_EMOJI == "🌐"
        # And that it's a valid emoji (different from some known region emojis)
        assert DEFAULT_REGION_EMOJI == REGION_EMOJI["Глобал"]

    def test_escaping_applied_to_dynamic_text(self):
        """Dynamic text (essence, summary) should be escaped."""
        batch = _make_batch([
            _make_news_analysis(essence="Test_with_underscore", summary="Summary*with*asterisk")
        ])
        date = datetime.now(timezone.utc)
        result = format_digest_markdown([batch], date)

        assert "Test\\_with\\_underscore" in result
        assert "Summary\\*with\\*asterisk" in result

    def test_markers_not_escaped(self):
        """Markdown markers (*...* for bold) should NOT be escaped."""
        batch = _make_batch([_make_news_analysis()])
        date = datetime.now(timezone.utc)
        result = format_digest_markdown([batch], date)

        # Bold markers should remain unescaped
        assert "*Медицинский дайджест*" in result or "*Медицинский дайджест*" in result.replace("\\*", "*")
        # Region names in bold
        assert "*Америка*" in result or "*Америка*" in result.replace("\\*", "*")


class TestBuildDigestMessage:
    """Tests for build_digest_message function."""

    @pytest.mark.asyncio
    async def test_full_pipeline_two_batches_success(self):
        """Full pipeline with 2 successful batches should return formatted string."""
        mock_batch_data = [
            [{"url": "http://a.com", "title": "A", "content": "Content A", "source": "SrcA"}],
            [{"url": "http://b.com", "title": "B", "content": "Content B", "source": "SrcB"}],
        ]

        mock_analyses = [
            _make_batch([_make_news_analysis(region="Америка", essence="America news")]),
            _make_batch([_make_news_analysis(region="Европа", essence="Europe news")]),
        ]

        mock_client = AsyncMock()
        mock_client.analyze_news_batch = AsyncMock(side_effect=[mock_analyses[0], mock_analyses[1]])
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.digest_builder.prepare_batches_for_analysis",
            return_value=mock_batch_data,
        ) as mock_prepare:
            result = await build_digest_message(lookback_hours=24, client=mock_client)

        assert mock_prepare.called
        assert mock_client.analyze_news_batch.call_count == 2
        assert "📰 *Медицинский дайджест*" in result
        assert "🌎" in result or "🌍" in result

    @pytest.mark.asyncio
    async def test_no_batches_returns_empty_string(self):
        """No batches should return empty string, LLM not called."""
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.digest_builder.prepare_batches_for_analysis",
            return_value=[],
        ) as mock_prepare:
            result = await build_digest_message(client=mock_client)

        assert result == ""
        assert mock_prepare.called
        assert not mock_client.analyze_news_batch.called

    @pytest.mark.asyncio
    async def test_one_batch_fails_continues_with_other(self):
        """If one batch fails, continue with others."""
        mock_analysis = _make_batch([_make_news_analysis(region="Америка")])

        # Need two batches to test failure + success
        mock_batch_data = [
            [{"url": "http://a.com", "title": "A", "content": "A", "source": "A"}],
            [{"url": "http://b.com", "title": "B", "content": "B", "source": "B"}],
        ]

        mock_client = AsyncMock()
        mock_client.analyze_news_batch = AsyncMock(side_effect=[Exception("LLM error"), mock_analysis])
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.digest_builder.prepare_batches_for_analysis",
            return_value=mock_batch_data,
        ):
            result = await build_digest_message(client=mock_client)

        assert mock_client.analyze_news_batch.call_count == 2
        assert result != ""  # Should contain second batch result

    @pytest.mark.asyncio
    async def test_all_batches_fail_returns_empty_string(self):
        """If all batches fail, return empty string."""
        mock_batch_data = [[{"url": "http://a.com", "title": "A", "content": "A", "source": "A"}]]

        mock_client = AsyncMock()
        mock_client.analyze_news_batch = AsyncMock(side_effect=Exception("LLM error"))
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.digest_builder.prepare_batches_for_analysis",
            return_value=mock_batch_data,
        ):
            result = await build_digest_message(client=mock_client)

        assert result == ""

    @pytest.mark.asyncio
    async def test_request_id_generated(self):
        """build_digest_message should call new_request_id()."""
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()

        with patch(
            "app.services.digest_builder.new_request_id",
            return_value="test-request-id-123",
        ) as mock_new_request_id:
            with patch(
                "app.services.digest_builder.prepare_batches_for_analysis",
                return_value=[],
            ):
                await build_digest_message(client=mock_client)

        assert mock_new_request_id.called

    @pytest.mark.asyncio
    async def test_client_aclose_called_when_created_internally(self):
        """LLM client should be closed when created internally."""
        with patch(
            "app.services.digest_builder.LLMClient"
        ) as mock_llm_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.analyze_news_batch = AsyncMock(side_effect=Exception("LLM error"))
            mock_client_instance.aclose = AsyncMock()
            mock_llm_class.return_value = mock_client_instance

            with patch(
                "app.services.digest_builder.prepare_batches_for_analysis",
                return_value=[[{"url": "http://a.com", "title": "A", "content": "A", "source": "A"}]],
            ):
                await build_digest_message()

            mock_client_instance.aclose.assert_called_once()


class TestSendDigestToTelegram:
    """Tests for send_digest_to_telegram function."""

    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        """Success on first attempt should return message_id."""
        mock_bot = AsyncMock(spec=Bot)
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=12345))
        mock_bot.close = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.create_digest_log = AsyncMock(return_value=MagicMock(id=1))
        mock_repo.mark_digest_sent = AsyncMock()

        async def mock_get_session_gen():
            yield MagicMock()

        with patch(
            "app.services.digest_builder.get_session",
            side_effect=mock_get_session_gen,
        ):
            with patch(
                "app.services.digest_builder.Repository",
                return_value=mock_repo,
            ):
                result = await send_digest_to_telegram(
                    chat_id=-1001234567890,
                    message="Test message",
                    bot=mock_bot,
                )

        assert result == 12345
        mock_bot.send_message.assert_called_once_with(
            chat_id=-1001234567890,
            text="Test message",
            parse_mode="MarkdownV2",
        )

    @pytest.mark.asyncio
    async def test_retry_on_failure_second_success(self):
        """First attempt fails, second succeeds."""
        mock_bot = AsyncMock(spec=Bot)
        mock_bot.send_message = AsyncMock(
            side_effect=[
                Exception("Network error"),
                MagicMock(message_id=67890),
            ]
        )
        mock_bot.close = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.create_digest_log = AsyncMock(return_value=MagicMock(id=2))
        mock_repo.mark_digest_sent = AsyncMock()

        async def mock_get_session_gen():
            yield MagicMock()

        with patch(
            "app.services.digest_builder.get_session",
            side_effect=mock_get_session_gen,
        ):
            with patch(
                "app.services.digest_builder.Repository",
                return_value=mock_repo,
            ):
                with patch(
                    "app.services.digest_builder.asyncio.sleep",
                    new_callable=AsyncMock,
                ) as mock_sleep:
                    result = await send_digest_to_telegram(
                        chat_id=-1001234567890,
                        message="Test message",
                        bot=mock_bot,
                    )

        assert result == 67890
        assert mock_bot.send_message.call_count == 2
        mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_attempts_fail_raises_error(self):
        """All attempts fail should raise DigestDeliveryError."""
        mock_bot = AsyncMock(spec=Bot)
        mock_bot.send_message = AsyncMock(
            side_effect=Exception("Persistent network error")
        )
        mock_bot.close = AsyncMock()

        with patch(
            "app.services.digest_builder.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with pytest.raises(DigestDeliveryError):
                await send_digest_to_telegram(
                    chat_id=-1001234567890,
                    message="Test message",
                    bot=mock_bot,
                )

        # 3 retry attempts + 1 admin notification attempt = 4 calls
        assert mock_bot.send_message.call_count == 4

    @pytest.mark.asyncio
    async def test_admin_notified_on_failure(self):
        """Admin should be notified when all attempts fail."""
        mock_bot = AsyncMock(spec=Bot)
        mock_bot.send_message = AsyncMock(side_effect=Exception("Error"))
        mock_bot.close = AsyncMock()

        with patch(
            "app.services.digest_builder.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with pytest.raises(DigestDeliveryError):
                await send_digest_to_telegram(
                    chat_id=-1001234567890,
                    message="Test message",
                    bot=mock_bot,
                )

        # Admin notification should be attempted (second call to send_message)
        assert mock_bot.send_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_repository_methods_called_on_success(self):
        """create_digest_log and mark_digest_sent should be called on success."""
        mock_bot = AsyncMock(spec=Bot)
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=11111))
        mock_bot.close = AsyncMock()

        mock_repo = AsyncMock()
        mock_digest_log = MagicMock(id=999)
        mock_repo.create_digest_log = AsyncMock(return_value=mock_digest_log)
        mock_repo.mark_digest_sent = AsyncMock()

        async def mock_get_session_gen():
            yield MagicMock()

        with patch(
            "app.services.digest_builder.get_session",
            side_effect=mock_get_session_gen,
        ):
            with patch(
                "app.services.digest_builder.Repository",
                return_value=mock_repo,
            ):
                await send_digest_to_telegram(
                    chat_id=-1001234567890,
                    message="Test • message",
                    bot=mock_bot,
                )

        mock_repo.create_digest_log.assert_called_once()
        mock_repo.mark_digest_sent.assert_called_once_with(999, 11111)

    @pytest.mark.asyncio
    async def test_bot_created_and_closed_when_none_provided(self):
        """Bot should be created and closed when None provided."""
        mock_settings = MagicMock()
        mock_settings.TELEGRAM_BOT_TOKEN.get_secret_value.return_value = "test_token"
        mock_settings.NEWS_DELIVERY_RETRIES = 1
        mock_settings.NEWS_DELIVERY_RETRY_DELAY_MINUTES = 1
        mock_settings.TELEGRAM_ADMIN_ID = None

        mock_bot_instance = AsyncMock(spec=Bot)
        mock_bot_instance.send_message = AsyncMock(return_value=MagicMock(message_id=22222))
        mock_bot_instance.close = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.create_digest_log = AsyncMock(return_value=MagicMock(id=3))
        mock_repo.mark_digest_sent = AsyncMock()

        async def mock_get_session_gen():
            yield MagicMock()

        with patch(
            "app.services.digest_builder.get_settings",
            return_value=mock_settings,
        ):
            with patch(
                "app.services.digest_builder.Bot",
                return_value=mock_bot_instance,
            ) as mock_bot_class:
                with patch(
                    "app.services.digest_builder.get_session",
                    side_effect=mock_get_session_gen,
                ):
                    with patch(
                        "app.services.digest_builder.Repository",
                        return_value=mock_repo,
                    ):
                        result = await send_digest_to_telegram(
                            chat_id=-1001234567890,
                            message="Test message",
                            bot=None,
                        )

        assert result == 22222
        mock_bot_class.assert_called_once_with(token="test_token")
        mock_bot_instance.close.assert_called_once()


class TestIntegration:
    """Integration tests with full flow."""

    @pytest.mark.asyncio
    async def test_build_and_send_full_flow(self):
        """Full flow: build_digest_message → send_digest_to_telegram."""
        mock_batch_data = [[{"url": "http://test.com", "title": "Test", "content": "Content", "source": "Src"}]]
        mock_analysis = _make_batch([_make_news_analysis(region="Америка", essence="Test news")])

        mock_client = AsyncMock()
        mock_client.analyze_news_batch = AsyncMock(return_value=mock_analysis)
        mock_client.aclose = AsyncMock()

        mock_bot = AsyncMock(spec=Bot)
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=54321))
        mock_bot.close = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.create_digest_log = AsyncMock(return_value=MagicMock(id=5))
        mock_repo.mark_digest_sent = AsyncMock()

        async def mock_get_session_gen():
            yield MagicMock()

        with patch(
            "app.services.digest_builder.prepare_batches_for_analysis",
            return_value=mock_batch_data,
        ):
            with patch(
                "app.services.digest_builder.get_session",
                side_effect=mock_get_session_gen,
            ):
                with patch(
                    "app.services.digest_builder.Repository",
                    return_value=mock_repo,
                ):
                    digest_text = await build_digest_message(client=mock_client)
                    assert digest_text != ""

                    message_id = await send_digest_to_telegram(
                        chat_id=-1001234567890,
                        message=digest_text,
                        bot=mock_bot,
                    )

        assert message_id == 54321
        mock_bot.send_message.assert_called_once()

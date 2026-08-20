"""Digest Builder Service for MedNews Secretary Agent.

Final module of News Pipeline: batches → LLM analysis → MarkdownV2 post →
Telegram delivery with retry → DB logging. Async-first implementation with
graceful error handling.
"""
import asyncio
import re
from datetime import datetime

from aiogram import Bot

from app.config import get_settings
from app.db.database import get_session
from app.db.repository import Repository
from app.llm.client import LLMClient
from app.llm.schemas import NewsAnalysisBatch
from app.logging_setup import get_logger as get_struct_logger
from app.logging_setup import new_request_id
from app.services.news_pipeline import prepare_batches_for_analysis


class DigestDeliveryError(RuntimeError):
    """Отправка дайджеста не удалась после всех retry."""

    pass


REGION_EMOJI: dict[str, str] = {
    "Америка": "🌎",
    "Европа": "🌍",
    "Россия": "🇷🇺",
    "Азия": "🌏",
    "Глобал": "🌐",
}

DEFAULT_REGION_EMOJI = "🌐"


def escape_markdown_v2(text: str) -> str:
    """Экранирует спецсимволы Telegram MarkdownV2.

    Escapes each special character from the set:
    _ * [ ] ( ) ~ > # + - = | { } . !

    Args:
        text: Text to escape.

    Returns:
        Escaped text safe for Telegram MarkdownV2.
    """
    # Characters that need escaping in MarkdownV2
    special_chars = r"_*\[\]()~>`#+\-=|{}.!"
    return re.sub(rf"([{re.escape(special_chars)}])", r"\\\1", text)


def format_digest_markdown(analyses: list[NewsAnalysisBatch], date: datetime) -> str:
    """Форматирует список анализов в MarkdownV2-пост, сгруппированный по регионам.

    Format:
    📰 *Медицинский дайджест* — YYYY-MM-DD

    🌎 *Америка*
    • {essence} — {scientific_summary_ru}
    • ...

    Args:
        analyses: List of NewsAnalysisBatch results from LLM.
        date: Date for the digest header (should be in user's timezone).

    Returns:
        Formatted MarkdownV2 string ready for Telegram send_message.
    """
    if not analyses:
        return ""

    # Group all articles by region
    region_articles: dict[str, list[tuple[str, str]]] = {}
    for batch in analyses:
        for article in batch.articles:
            region = article.region
            essence = escape_markdown_v2(article.essence)
            summary = escape_markdown_v2(article.scientific_summary_ru)
            if region not in region_articles:
                region_articles[region] = []
            region_articles[region].append((essence, summary))

    # Define stable region order
    region_order = ["Америка", "Европа", "Россия", "Азия", "Глобал"]

    # Build the message
    lines: list[str] = []

    # Header with date
    date_str = date.strftime("%Y-%m-%d")
    lines.append(f"📰 *Медицинский дайджест* — {date_str}")
    lines.append("")

    # Add sections for each region in order
    for region in region_order:
        if region not in region_articles:
            continue
        emoji = REGION_EMOJI.get(region, DEFAULT_REGION_EMOJI)
        escaped_region = escape_markdown_v2(region)
        lines.append(f"{emoji} *{escaped_region}*")
        for essence, summary in region_articles[region]:
            lines.append(f"• {essence} — {summary}")
        lines.append("")

    # Handle unknown regions (not in our predefined list)
    unknown_regions = set(region_articles.keys()) - set(region_order)
    for region in sorted(unknown_regions):
        emoji = DEFAULT_REGION_EMOJI
        escaped_region = escape_markdown_v2(region)
        lines.append(f"{emoji} *{escaped_region}*")
        for essence, summary in region_articles[region]:
            lines.append(f"• {essence} — {summary}")
        lines.append("")

    return "\n".join(lines).strip()


async def build_digest_message(lookback_hours: int = 24, client: LLMClient | None = None) -> str:
    """Полный pipeline: RSS → dedup → batches → LLM → MarkdownV2.

    Full pipeline:
    1. Generate and bind request_id
    2. Fetch and prepare batches via prepare_batches_for_analysis
    3. Analyze each batch via LLM (graceful failure on individual batch errors)
    4. Format results into MarkdownV2 post

    Args:
        lookback_hours: Hours to look back for RSS fetching (default 24).
        client: Optional LLMClient instance for DI/testing. If None, creates one internally.

    Returns:
        MarkdownV2-formatted digest string, or "" if nothing to analyze.
    """
    # Generate and bind request_id
    request_id = new_request_id()
    from structlog.contextvars import bind_contextvars

    bind_contextvars(request_id=request_id)

    logger = get_struct_logger("digest_builder")
    logger.info("Starting digest build pipeline", extra={"lookback_hours": lookback_hours})

    # Step 1: Prepare batches
    batches = await prepare_batches_for_analysis(lookback_hours=lookback_hours)

    if not batches:
        logger.warning("No batches to analyze")
        return ""

    logger.info(f"Prepared {len(batches)} batches for analysis")

    # Create LLM client if not provided
    should_close_client = client is None
    if should_close_client:
        client = LLMClient()

    try:
        # Step 2: Analyze each batch with graceful failure
        analyses: list[NewsAnalysisBatch] = []
        for i, batch in enumerate(batches):
            try:
                result = await client.analyze_news_batch(batch)
                analyses.append(result)
                logger.info(f"Batch {i + 1}/{len(batches)} analyzed successfully")
            except Exception as e:
                logger.warning(
                    f"Failed to analyze batch {i + 1}/{len(batches)}",
                    extra={"error": str(e), "batch_index": i},
                )
                # Continue with remaining batches (graceful failure)
                continue

        if not analyses:
            logger.error("No successful batch analyses")
            return ""

        # Step 3: Get current date in user's timezone for display
        settings = get_settings()
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(settings.TIMEZONE)
        current_date = datetime.now(tz)

        # Step 4: Format and return
        digest_text = format_digest_markdown(analyses, current_date)
        logger.info("Digest build completed", extra={"text_length": len(digest_text)})

        return digest_text
    finally:
        if should_close_client and client:
            await client.aclose()


async def send_digest_to_telegram(
    chat_id: int, message: str, bot: Bot | None = None
) -> int:
    """Отправка с retry. Возвращает message_id. Бросает DigestDeliveryError при провале.

    Sends digest message to Telegram with retry logic:
    - Total attempts = NEWS_DELIVERY_RETRIES (default 3)
    - Delay between attempts = NEWS_DELIVERY_RETRY_DELAY_MINUTES * 60 seconds

    On success: logs to DB via create_digest_log and mark_digest_sent.
    On failure: notifies TELEGRAM_ADMIN_ID (if available), raises DigestDeliveryError.

    Args:
        chat_id: Telegram chat/channel ID to send to.
        message: MarkdownV2-formatted message text.
        bot: Optional Bot instance for DI/testing. If None, creates one internally.

    Returns:
        message_id of the sent message.

    Raises:
        DigestDeliveryError: If all retry attempts fail.
    """
    settings = get_settings()
    logger = get_struct_logger("digest_builder")

    retries = settings.NEWS_DELIVERY_RETRIES
    delay_seconds = settings.NEWS_DELIVERY_RETRY_DELAY_MINUTES * 60

    last_exception: Exception | None = None
    message_id: int | None = None

    # Create bot if not provided
    should_close_bot = bot is None
    if should_close_bot:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())

    try:
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Sending digest to Telegram (attempt {attempt}/{retries})")
                response = await bot.send_message(
                    chat_id=chat_id, text=message, parse_mode="MarkdownV2"
                )
                message_id = response.message_id
                logger.info(f"Digest sent successfully, message_id={message_id}")
                break
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Send attempt {attempt}/{retries} failed",
                    extra={"error": str(e)},
                )
                if attempt < retries:
                    await asyncio.sleep(delay_seconds)

        if message_id is None:
            # All attempts failed
            logger.error(
                f"All {retries} send attempts failed",
                extra={"last_error": str(last_exception)},
            )

            # Try to notify admin
            admin_id = settings.TELEGRAM_ADMIN_ID
            if admin_id:
                try:
                    error_msg = (
                        f"CRITICAL: Failed to send digest after {retries} attempts. "
                        f"Error: {last_exception}"
                    )
                    await bot.send_message(
                        chat_id=admin_id,
                        text=error_msg,
                        parse_mode=None,
                    )
                    logger.info("Admin notification sent")
                except Exception as admin_error:
                    logger.warning(
                        "Failed to notify admin",
                        extra={"error": str(admin_error)},
                    )

            raise DigestDeliveryError(
                f"Failed to send digest after {retries} attempts: {last_exception}"
            )

        # Success: log to DB
        async for session in get_session():
            repo = Repository(session)
            # Count total articles from the message (rough estimate from bullet points)
            article_count = message.count("• ")
            batch_count = max(1, article_count // 5)  # Rough estimate
            digest_log = await repo.create_digest_log(
                chat_id=chat_id,
                article_count=article_count,
                batch_count=batch_count,
                status="pending",
            )
            await repo.mark_digest_sent(digest_log.id, message_id)
            logger.info(
                "Digest logged to DB",
                extra={"digest_id": digest_log.id, "message_id": message_id},
            )
            break

        return message_id

    finally:
        if should_close_bot and bot:
            await bot.close()

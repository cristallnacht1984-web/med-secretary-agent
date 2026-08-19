"""Async LLM client for MedNews Secretary Agent."""
import asyncio
import time
from typing import Any

from openai import APIStatusError, APITimeoutError, AsyncOpenAI

from app.config import Settings, get_settings
from app.llm.prompts import (
    INTENT_CLASSIFICATION_SYSTEM_PROMPT,
    NEWS_ANALYSIS_SYSTEM_PROMPT,
    REMINDER_SUMMARY_SYSTEM_PROMPT,
)
from app.llm.schemas import (
    IntentClassification,
    NewsAnalysisBatch,
    ReminderSummary,
)
from app.logging_setup import get_logger, new_request_id


class RateLimiter:
    """Rate limiter with RPM and TPM tracking."""

    def __init__(self, rpm: int, tpm: int):
        self.rpm = rpm
        self.tpm = tpm
        self._requests: list[float] = []
        self._tokens: list[tuple[float, int]] = []
        self._lock = asyncio.Lock()

    async def acquire(self, tokens_count: int = 0) -> None:
        """Wait until rate limit allows request."""
        async with self._lock:
            now = time.time()
            window_start = now - 60.0

            # Clean old requests
            self._requests = [t for t in self._requests if t > window_start]
            self._tokens = [(t, c) for t, c in self._tokens if t > window_start]

            # Check RPM
            while len(self._requests) >= self.rpm:
                oldest = self._requests[0]
                wait_time = oldest + 60.0 - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    window_start = now - 60.0
                    self._requests = [t for t in self._requests if t > window_start]
                    self._tokens = [(t, c) for t, c in self._tokens if t > window_start]

            # Check TPM
            total_tokens = sum(c for _, c in self._tokens)
            while total_tokens + tokens_count > self.tpm:
                oldest = self._tokens[0][0]
                wait_time = oldest + 60.0 - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    window_start = now - 60.0
                    self._requests = [t for t in self._requests if t > window_start]
                    self._tokens = [(t, c) for t, c in self._tokens if t > window_start]
                    total_tokens = sum(c for _, c in self._tokens)

            # Record this request
            self._requests.append(now)
            if tokens_count > 0:
                self._tokens.append((now, tokens_count))


class LLMClient:
    """Async-клиент Qwen 3.6 через OpenAI-compatible API."""

    def __init__(self, settings: Settings | None = None):
        """Initialize LLM client with settings."""
        self._settings = settings or get_settings()
        self._client = AsyncOpenAI(
            base_url=self._settings.LLM_BASE_URL,
            api_key=self._settings.LLM_API_KEY.get_secret_value(),
            timeout=self._settings.LLM_TIMEOUT_ANALYSIS,
        )
        self._model = self._settings.LLM_MODEL_NAME
        self._rate_limiter = RateLimiter(
            self._settings.LLM_RATE_LIMIT_RPM,
            self._settings.LLM_RATE_LIMIT_TPM,
        )
        self._logger = get_logger("llm")

    async def _retry_with_backoff(
        self, func: callable, max_retries: int, base_delay: float = 1.0
    ) -> Any:
        """Execute function with exponential backoff retry on API errors."""
        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                return await func()
            except (APITimeoutError, APIStatusError) as e:
                last_exception = e
                # Retry only on 5xx errors for APIStatusError
                if isinstance(e, APIStatusError) and e.status_code < 500:
                    raise
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    self._logger.warning(
                        f"LLM API error (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay}s",
                        error_type=type(e).__name__,
                    )
                    await asyncio.sleep(delay)
                else:
                    break
            except ConnectionRefusedError as e:
                last_exception = e
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    self._logger.warning(
                        f"Connection refused (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay}s",
                    )
                    await asyncio.sleep(delay)
                else:
                    break
        raise last_exception

    async def _call_llm(
        self,
        system_prompt: str,
        user_content: str,
        response_model: type,
        timeout: int,
    ) -> Any:
        """Make LLM call with rate limiting and validation."""
        request_id = new_request_id()

        async def _make_request():
            await self._rate_limiter.acquire()

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=self._settings.LLM_TEMPERATURE_ANALYSIS,
                max_tokens=self._settings.LLM_MAX_TOKENS,
                timeout=timeout,
            )

            # Extract token counts
            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = response.usage.completion_tokens if response.usage else 0

            # Log token usage
            self._logger.info(
                "LLM request completed",
                request_id=request_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

            # Parse JSON response
            content = response.choices[0].message.content
            return response_model.model_validate_json(content)

        return await self._retry_with_backoff(
            _make_request, self._settings.LLM_MAX_RETRIES
        )

    async def analyze_news_batch(self, articles: list[dict]) -> NewsAnalysisBatch:
        """Analyze batch of news articles.

        Args:
            articles: List of article dicts with url, title, content, source.

        Returns:
            NewsAnalysisBatch with 3-5 analyzed articles.
        """
        user_content = "Проанализируй следующие статьи:\n\n"
        for i, article in enumerate(articles, 1):
            user_content += f"{i}. URL: {article.get('url', 'N/A')}\n"
            user_content += f"   Title: {article.get('title', 'N/A')}\n"
            user_content += f"   Content: {article.get('content', 'N/A')}\n"
            user_content += f"   Source: {article.get('source', 'N/A')}\n\n"

        return await self._call_llm(
            NEWS_ANALYSIS_SYSTEM_PROMPT,
            user_content,
            NewsAnalysisBatch,
            self._settings.LLM_TIMEOUT_ANALYSIS,
        )

    async def classify_intent(self, message: str) -> IntentClassification:
        """Classify user intent.

        Args:
            message: User message text.

        Returns:
            IntentClassification with intent, confidence, parameters.
        """
        user_content = f"Классифицируй намерение пользователя:\n\n{message}"

        return await self._call_llm(
            INTENT_CLASSIFICATION_SYSTEM_PROMPT,
            user_content,
            IntentClassification,
            self._settings.LLM_TIMEOUT_CLASSIFICATION,
        )

    async def summarize_reminder(self, event: dict) -> ReminderSummary:
        """Summarize reminder event.

        Args:
            event: Event dict with title, start_time, description, location.

        Returns:
            ReminderSummary with event details and tips.
        """
        user_content = (
            f"Создай резюме напоминания:\n\n"
            f"Title: {event.get('title', 'N/A')}\n"
            f"Start: {event.get('start_time', 'N/A')}\n"
            f"Description: {event.get('description', 'N/A')}\n"
            f"Location: {event.get('location', 'N/A')}"
        )

        return await self._call_llm(
            REMINDER_SUMMARY_SYSTEM_PROMPT,
            user_content,
            ReminderSummary,
            self._settings.LLM_TIMEOUT_REMINDER,
        )

    async def aclose(self) -> None:
        """Close the LLM client gracefully."""
        await self._client.close()

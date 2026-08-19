"""LLM-модуль MedNews Secretary Agent."""

from app.llm.client import LLMClient
from app.llm.prompts import (
    INTENT_CLASSIFICATION_SYSTEM_PROMPT,
    NEWS_ANALYSIS_SYSTEM_PROMPT,
    REMINDER_SUMMARY_SYSTEM_PROMPT,
)
from app.llm.schemas import (
    IntentClassification,
    NewsAnalysis,
    NewsAnalysisBatch,
    ReminderSummary,
)

__all__ = [
    "INTENT_CLASSIFICATION_SYSTEM_PROMPT",
    "IntentClassification",
    "LLMClient",
    "NEWS_ANALYSIS_SYSTEM_PROMPT",
    "NewsAnalysis",
    "NewsAnalysisBatch",
    "REMINDER_SUMMARY_SYSTEM_PROMPT",
    "ReminderSummary",
]

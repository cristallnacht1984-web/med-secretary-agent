"""Pydantic schemas for LLM response validation."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NewsAnalysis(BaseModel):
    """Модель анализа новостной статьи.

    Attributes:
        article_url: URL статьи (минимум 1 символ).
        region: Географический регион новости.
        source: Название источника (минимум 1 символ).
        essence: Краткая суть новости (минимум 1 символ).
        significance: Уровень значимости новости.
        scientific_summary_ru: Научное резюме на русском (минимум 1 символ).
    """

    article_url: str = Field(..., min_length=1)
    region: Literal["Америка", "Европа", "Россия", "Азия", "Глобал"]
    source: str = Field(..., min_length=1)
    essence: str = Field(..., min_length=1)
    significance: Literal["High", "Medium", "Low"]
    scientific_summary_ru: str = Field(..., min_length=1)


class NewsAnalysisBatch(BaseModel):
    """Модель пакета анализов новостей.

    Attributes:
        articles: Список анализов статей (от 3 до 5 штук).
    """

    articles: list[NewsAnalysis] = Field(..., min_length=3, max_length=5)


class IntentClassification(BaseModel):
    """Модель классификации намерений пользователя.

    Attributes:
        intent: Тип намерения пользователя.
        confidence: Уверенность классификации (от 0.0 до 1.0).
        parameters: Дополнительные параметры намерения.
    """

    intent: Literal[
        "find_slots",
        "create_event",
        "update_event",
        "cancel_event",
        "set_reminder",
        "other",
    ]
    confidence: float = Field(..., ge=0.0, le=1.0)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ReminderSummary(BaseModel):
    """Модель сводки напоминания.

    Attributes:
        event_title: Название события (минимум 1 символ).
        event_start: Время начала события в формате ISO 8601.
        summary: Краткое описание напоминания (минимум 1 символ).
        preparation_tips: Список советов по подготовке (может отсутствовать).
    """

    event_title: str = Field(..., min_length=1)
    event_start: datetime
    summary: str = Field(..., min_length=1)
    preparation_tips: list[str] | None = None

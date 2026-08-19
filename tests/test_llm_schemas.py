"""Tests for LLM Pydantic schemas."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.llm.schemas import (
    IntentClassification,
    NewsAnalysis,
    NewsAnalysisBatch,
    ReminderSummary,
)


class TestNewsAnalysis:
    """Тесты для модели NewsAnalysis."""

    def test_valid_news_analysis(self):
        """Валидные данные NewsAnalysis → OK."""
        data = {
            "article_url": "https://example.com/news/123",
            "region": "Россия",
            "source": "РИА Новости",
            "essence": "Новые разработки в области ИИ",
            "significance": "High",
            "scientific_summary_ru": "Краткое научное резюме на русском языке",
        }
        model = NewsAnalysis(**data)
        assert model.article_url == data["article_url"]
        assert model.region == data["region"]
        assert model.source == data["source"]
        assert model.essence == data["essence"]
        assert model.significance == data["significance"]
        assert model.scientific_summary_ru == data["scientific_summary_ru"]

    def test_invalid_region(self):
        """Невалидный region → ValidationError."""
        data = {
            "article_url": "https://example.com/news/123",
            "region": "Африка",  # Недопустимое значение
            "source": "РИА Новости",
            "essence": "Новые разработки в области ИИ",
            "significance": "High",
            "scientific_summary_ru": "Краткое научное резюме на русском языке",
        }
        with pytest.raises(ValidationError):
            NewsAnalysis(**data)

    def test_invalid_significance(self):
        """Невалидный significance → ValidationError."""
        data = {
            "article_url": "https://example.com/news/123",
            "region": "Россия",
            "source": "РИА Новости",
            "essence": "Новые разработки в области ИИ",
            "significance": "Med",  # Должно быть Medium
            "scientific_summary_ru": "Краткое научное резюме на русском языке",
        }
        with pytest.raises(ValidationError):
            NewsAnalysis(**data)

    @pytest.mark.parametrize("field_name", ["source", "essence", "scientific_summary_ru", "article_url"])
    def test_empty_string_fields(self, field_name):
        """Пустые строки контентных полей → ValidationError."""
        data = {
            "article_url": "https://example.com/news/123",
            "region": "Россия",
            "source": "РИА Новости",
            "essence": "Новые разработки в области ИИ",
            "significance": "High",
            "scientific_summary_ru": "Краткое научное резюме на русском языке",
        }
        data[field_name] = ""
        with pytest.raises(ValidationError):
            NewsAnalysis(**data)


class TestNewsAnalysisBatch:
    """Тесты для модели NewsAnalysisBatch."""

    def test_batch_with_3_articles(self):
        """Пакет с 3 статьями → OK."""
        articles = [
            {
                "article_url": f"https://example.com/news/{i}",
                "region": "Россия",
                "source": f"Источник {i}",
                "essence": f"Суть новости {i}",
                "significance": "High",
                "scientific_summary_ru": f"Резюме {i}",
            }
            for i in range(3)
        ]
        batch = NewsAnalysisBatch(articles=articles)
        assert len(batch.articles) == 3

    def test_batch_with_5_articles(self):
        """Пакет с 5 статьями → OK."""
        articles = [
            {
                "article_url": f"https://example.com/news/{i}",
                "region": "Европа",
                "source": f"Источник {i}",
                "essence": f"Суть новости {i}",
                "significance": "Medium",
                "scientific_summary_ru": f"Резюме {i}",
            }
            for i in range(5)
        ]
        batch = NewsAnalysisBatch(articles=articles)
        assert len(batch.articles) == 5

    def test_batch_with_2_articles_fails(self):
        """Пакет с 2 статьями → ValidationError."""
        articles = [
            {
                "article_url": f"https://example.com/news/{i}",
                "region": "Россия",
                "source": f"Источник {i}",
                "essence": f"Суть новости {i}",
                "significance": "High",
                "scientific_summary_ru": f"Резюме {i}",
            }
            for i in range(2)
        ]
        with pytest.raises(ValidationError):
            NewsAnalysisBatch(articles=articles)

    def test_batch_with_6_articles_fails(self):
        """Пакет с 6 статьями → ValidationError."""
        articles = [
            {
                "article_url": f"https://example.com/news/{i}",
                "region": "Россия",
                "source": f"Источник {i}",
                "essence": f"Суть новости {i}",
                "significance": "High",
                "scientific_summary_ru": f"Резюме {i}",
            }
            for i in range(6)
        ]
        with pytest.raises(ValidationError):
            NewsAnalysisBatch(articles=articles)


class TestIntentClassification:
    """Тесты для модели IntentClassification."""

    @pytest.mark.parametrize(
        "intent_value",
        ["find_slots", "create_event", "update_event", "cancel_event", "set_reminder", "other"],
    )
    def test_valid_intents(self, intent_value):
        """Каждый из 6 Literal intent валиден."""
        data = {"intent": intent_value, "confidence": 0.95}
        model = IntentClassification(**data)
        assert model.intent == intent_value

    def test_invalid_intent(self):
        """Невалидный intent → ValidationError."""
        data = {"intent": "unknown_intent", "confidence": 0.95}
        with pytest.raises(ValidationError):
            IntentClassification(**data)

    @pytest.mark.parametrize("confidence_value", [0.0, 1.0])
    def test_boundary_confidence(self, confidence_value):
        """confidence 0.0 и 1.0 → OK."""
        data = {"intent": "find_slots", "confidence": confidence_value}
        model = IntentClassification(**data)
        assert model.confidence == confidence_value

    @pytest.mark.parametrize("confidence_value", [-0.1, 1.1])
    def test_invalid_confidence(self, confidence_value):
        """confidence -0.1 и 1.1 → ValidationError."""
        data = {"intent": "find_slots", "confidence": confidence_value}
        with pytest.raises(ValidationError):
            IntentClassification(**data)

    def test_parameters_default_factory(self):
        """parameters default == {} и независимость инстансов."""
        model1 = IntentClassification(intent="find_slots", confidence=0.9)
        model2 = IntentClassification(intent="create_event", confidence=0.8)
        assert model1.parameters == {}
        assert model2.parameters == {}
        # Проверка независимости
        model1.parameters["key1"] = "value1"
        assert model2.parameters == {}
        assert "key1" not in model2.parameters


class TestReminderSummary:
    """Тесты для модели ReminderSummary."""

    def test_valid_reminder_summary(self):
        """Валидные данные ReminderSummary → OK."""
        data = {
            "event_title": "Встреча с врачом",
            "event_start": "2025-01-15T10:00:00",
            "summary": "Плановый осмотр у терапевта",
            "preparation_tips": ["Взять паспорт", "Прийти за 15 минут"],
        }
        model = ReminderSummary(**data)
        assert model.event_title == data["event_title"]
        assert isinstance(model.event_start, datetime)
        assert model.summary == data["summary"]
        assert model.preparation_tips == data["preparation_tips"]

    def test_event_start_from_iso_string(self):
        """event_start из ISO-строки → корректный datetime."""
        iso_string = "2025-06-20T14:30:00"
        data = {
            "event_title": "Конференция",
            "event_start": iso_string,
            "summary": "Участие в конференции по ИИ",
        }
        model = ReminderSummary(**data)
        assert isinstance(model.event_start, datetime)
        assert model.event_start.year == 2025
        assert model.event_start.month == 6
        assert model.event_start.day == 20
        assert model.event_start.hour == 14
        assert model.event_start.minute == 30

    def test_preparation_tips_none(self):
        """preparation_tips=None → OK."""
        data = {
            "event_title": "Звонок коллеге",
            "event_start": "2025-01-15T10:00:00",
            "summary": "Обсуждение проекта",
        }
        model = ReminderSummary(**data)
        assert model.preparation_tips is None


class TestSerialization:
    """Тесты сериализации и интеграционные тесты."""

    def test_model_dump_news_analysis(self):
        """model_dump() возвращает ожидаемый dict для NewsAnalysis."""
        data = {
            "article_url": "https://example.com/news/123",
            "region": "Азия",
            "source": "Asia News",
            "essence": "Технологический прорыв",
            "significance": "Low",
            "scientific_summary_ru": "Научное описание",
        }
        model = NewsAnalysis(**data)
        dumped = model.model_dump()
        assert dumped == data

    def test_model_dump_intent_classification(self):
        """model_dump() возвращает ожидаемый dict для IntentClassification."""
        data = {"intent": "set_reminder", "confidence": 0.87, "parameters": {"time": "10:00"}}
        model = IntentClassification(**data)
        dumped = model.model_dump()
        assert dumped == data

    def test_model_validate_json_news_analysis(self):
        """ИНТЕГРАЦИОННЫЙ: NewsAnalysis.model_validate_json(json_str) → OK."""
        json_str = json.dumps(
            {
                "article_url": "https://example.com/news/456",
                "region": "Глобал",
                "source": "Global News",
                "essence": "Мировые события",
                "significance": "Medium",
                "scientific_summary_ru": "Глобальное резюме",
            }
        )
        model = NewsAnalysis.model_validate_json(json_str)
        assert model.article_url == "https://example.com/news/456"
        assert model.region == "Глобал"
        assert model.significance == "Medium"

    def test_model_validate_json_intent_classification(self):
        """ИНТЕГРАЦИОННЫЙ: IntentClassification.model_validate_json(json_str) → OK."""
        json_str = json.dumps({"intent": "cancel_event", "confidence": 0.92, "parameters": {}})
        model = IntentClassification.model_validate_json(json_str)
        assert model.intent == "cancel_event"
        assert model.confidence == 0.92
        assert model.parameters == {}

    def test_model_validate_json_reminder_summary(self):
        """ИНТЕГРАЦИОННЫЙ: ReminderSummary.model_validate_json(json_str) → OK."""
        json_str = json.dumps(
            {
                "event_title": "Вебинар",
                "event_start": "2025-03-10T18:00:00",
                "summary": "Онлайн-вебинар по машинному обучению",
                "preparation_tips": ["Проверить микрофон", "Подготовить вопросы"],
            }
        )
        model = ReminderSummary.model_validate_json(json_str)
        assert model.event_title == "Вебинар"
        assert isinstance(model.event_start, datetime)
        assert model.preparation_tips == ["Проверить микрофон", "Подготовить вопросы"]

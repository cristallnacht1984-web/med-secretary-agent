"""Тесты для модуля app.llm.prompts."""

import re

from app.llm.prompts import (
    INTENT_CLASSIFICATION_SYSTEM_PROMPT,
    NEWS_ANALYSIS_SYSTEM_PROMPT,
    REMINDER_SUMMARY_SYSTEM_PROMPT,
)


def test_news_analysis_prompt_is_string() -> None:
    """Проверка что NEWS_ANALYSIS_SYSTEM_PROMPT — строка."""
    assert isinstance(NEWS_ANALYSIS_SYSTEM_PROMPT, str)


def test_intent_classification_prompt_is_string() -> None:
    """Проверка что INTENT_CLASSIFICATION_SYSTEM_PROMPT — строка."""
    assert isinstance(INTENT_CLASSIFICATION_SYSTEM_PROMPT, str)


def test_reminder_summary_prompt_is_string() -> None:
    """Проверка что REMINDER_SUMMARY_SYSTEM_PROMPT — строка."""
    assert isinstance(REMINDER_SUMMARY_SYSTEM_PROMPT, str)


def test_news_analysis_contains_required_fields() -> None:
    """Проверка наличия обязательных полей в промпте анализа новостей."""
    required_fields = [
        "article_url",
        "region",
        "source",
        "essence",
        "significance",
        "scientific_summary_ru",
    ]
    for field in required_fields:
        assert field in NEWS_ANALYSIS_SYSTEM_PROMPT, f"Missing field: {field}"


def test_intent_classification_contains_all_intents() -> None:
    """Проверка наличия всех шести намерений в промпте классификации."""
    intents = ["find_slots", "create_event", "update_event", "cancel_event", "set_reminder", "other"]
    for intent in intents:
        assert intent in INTENT_CLASSIFICATION_SYSTEM_PROMPT, f"Missing intent: {intent}"


def test_reminder_summary_contains_required_fields() -> None:
    """Проверка наличия обязательных полей в промпте напоминаний."""
    required_fields = ["event_title", "event_start", "summary", "preparation_tips"]
    for field in required_fields:
        assert field in REMINDER_SUMMARY_SYSTEM_PROMPT, f"Missing field: {field}"


def test_prompts_length_bounds() -> None:
    """Проверка длины промптов в заданных диапазонах."""
    news_len = len(NEWS_ANALYSIS_SYSTEM_PROMPT)
    intent_len = len(INTENT_CLASSIFICATION_SYSTEM_PROMPT)
    reminder_len = len(REMINDER_SUMMARY_SYSTEM_PROMPT)

    assert 400 <= news_len <= 800, f"NEWS_ANALYSIS length {news_len} not in [400, 800]"
    assert 300 <= intent_len <= 600, f"INTENT_CLASSIFICATION length {intent_len} not in [300, 600]"
    assert 300 <= reminder_len <= 500, f"REMINDER_SUMMARY length {reminder_len} not in [300, 500]"


def test_no_variable_substitutions() -> None:
    """Проверка отсутствия фигурных скобок для подстановок переменных."""
    pattern = r"\{[^{}]+\}"
    assert re.search(pattern, NEWS_ANALYSIS_SYSTEM_PROMPT) is None
    assert re.search(pattern, INTENT_CLASSIFICATION_SYSTEM_PROMPT) is None
    assert re.search(pattern, REMINDER_SUMMARY_SYSTEM_PROMPT) is None


def test_russian_language_in_prompts() -> None:
    """Проверка наличия кириллицы во всех промптах."""
    cyrillic_pattern = r"[\u0400-\u04FF]"
    assert re.search(cyrillic_pattern, NEWS_ANALYSIS_SYSTEM_PROMPT) is not None
    assert re.search(cyrillic_pattern, INTENT_CLASSIFICATION_SYSTEM_PROMPT) is not None
    assert re.search(cyrillic_pattern, REMINDER_SUMMARY_SYSTEM_PROMPT) is not None


def test_constants_are_uppercase() -> None:
    """Проверка что имена констант в UPPER_CASE."""
    import app.llm.prompts as prompts_module

    constant_names = [
        "NEWS_ANALYSIS_SYSTEM_PROMPT",
        "INTENT_CLASSIFICATION_SYSTEM_PROMPT",
        "REMINDER_SUMMARY_SYSTEM_PROMPT",
    ]
    module_attrs = dir(prompts_module)
    for name in constant_names:
        assert name in module_attrs, f"Constant {name} not found in module"
        assert name.isupper(), f"Constant {name} is not UPPER_CASE"


def test_prompts_mention_structured_output() -> None:
    """Проверка упоминания structured output в каждом промпте."""
    structured_keywords = ["tool_calls", "function_calling", "structured output", "structured"]
    
    for prompt in [NEWS_ANALYSIS_SYSTEM_PROMPT, INTENT_CLASSIFICATION_SYSTEM_PROMPT, REMINDER_SUMMARY_SYSTEM_PROMPT]:
        prompt_lower = prompt.lower()
        has_keyword = any(kw in prompt_lower for kw in structured_keywords)
        assert has_keyword, f"Prompt missing structured output mention: {prompt[:50]}..."

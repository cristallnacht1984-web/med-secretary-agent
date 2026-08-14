# MedNews Secretary Agent

Асинхронный Telegram-бот для ежедневного аналитического дайджеста медицинских новостей + личный секретарь-календарь.

## Требования

- Python 3.11+
- Локальная LLM Qwen 3.6 через OpenAI-compatible API

## Установка

```bash
pip install -e ".[dev]"
```

## Конфигурация

1. Скопируйте `.env.example` в `.env`:
   ```bash
   cp .env.example .env
   ```

2. Заполните `.env` своими значениями (особенно секреты Telegram и Google).

## Запуск тестов

```bash
pytest -v
pytest --cov=app --cov-report=term-missing
```

## Линтинг

```bash
ruff check .
```

## Структура проекта

```
med_secretary/
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
├── app/
│   ├── __init__.py
│   └── config.py
└── tests/
    ├── __init__.py
    └── test_config.py
```

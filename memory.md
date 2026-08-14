# MEMORY — Institutional Knowledge MedNews Secretary Agent

ЭТОТ ФАЙЛ ЧИТАЕТСЯ В ПЕРВУЮ ОЧЕРЕДЬ В НАЧАЛЕ КАЖДОЙ СЕССИИ.
Он содержит накопленные архитектурные решения, зафиксированные проблемы и методологию работы.

## 1. ГОТОВЫЕ МОДУЛИ (НЕ МОДИФИЦИРОВАТЬ БЕЗ ЯВНОЙ ПРИЧИНЫ)

| Модуль | Статус | Ключевые контракты |
|---|---|---|
| `app/config.py` | ✅ DONE | pydantic-settings v2, @lru_cache, TIMEZONE через zoneinfo, SecretStr для секретов, TELEGRAM_ALLOWED_USER_IDS парсится из JSON. Публичный API: `get_settings() -> Settings` |
| `app/logging_setup.py` | ✅ DONE | structlog + JSON, request_id через contextvars, маскирование секретов (подстроки: api_key, token, password, secret, authorization, credentials), RotatingFileHandler(5MB, 5 backups), UTC timestamp. API: `setup_logging()`, `get_logger(name)`, `new_request_id()` |
| `app/health.py` | ✅ DONE | aiohttp server: `/health`, `/health/live` (loop_latency check), `/health/ready` (settings/required/db_url/google_creds), middleware request_id, graceful shutdown через signal handlers |
| `tests/test_config.py` | ✅ DONE | 21 тест + интеграционный test_logging_imports_settings, autouse фикстура clean_env_and_cache |
| `tests/test_logging.py` | ✅ DONE | 8 тестов: JSON mode, request_id, masking, debug, rotation, level filter, stdlib bridge |
| `tests/test_health.py` | ✅ DONE | 22 теста: все эндпоинты, edge cases, graceful shutdown, loop latency > 5.0 |

## 2. МЕТОДОЛОГИЯ РАБОТЫ СЕССИИ (ТЕХЛИДА)

### Шаг 1: Получение направления от оркестратора
Оркестратор даёт:
- Номер задачи и место в STARTUP ORDER
- Цель (objective)
- Архитектурные ограничения
- Acceptance criteria
- Список защищённых файлов

### Шаг 2: Формирование ТЗ для кодера
Сессия САМА формирует промпт кодеру, обязательно включая:
1. Ссылку на этот memory.md и TZ.md/AGENTS.md
2. Список защищённых файлов (ЗАПРЕЩЕНО изменять)
3. Точные пути создаваемых файлов
4. Публичный API нового модуля
5. Требования к тестам (сценарии + autouse фикстуры)
6. Acceptance criteria (pytest, coverage ≥80%, ruff, git diff)
7. Формат отчёта кодера → сессии

### Шаг 3: Валидация результата кодера
Сессия проверяет:
- `pytest -v` все тесты зелёные (включая РЕГРЕССИЮ: test_config, test_logging, test_health)
- `pytest --cov=app.new_module` ≥ 80%
- `ruff check .` = 0 ошибок
- `git diff` защищённых файлов пустой
- Архитектурная проверка: нет запрещённых импортов, нет хардкода, правильный паттерн async
- Если всё ок — формирует ФИНАЛЬНЫЙ ОТЧЁТ оркестратору

### Шаг 4: Фиксация результата
Сессия ОБЯЗАТЕЛЬНО коммитит результат: `git add . && git commit -m "feat: Task N description"`
Это предотвращает утерю состояния между сессиями (см. раздел "Зафиксированные проблемы").

## 3. АРХИТЕКТУРНЫЕ ПРИНЦИПЫ (обязательные для всех новых модулей)

### 3.1 Единственный источник конфигурации
- ВСЕ настройки только через `Settings` из `app/config.py`
- Никакого хардкода TZ (использовать `settings.TIMEZONE`)
- Секреты читать через `.get_secret_value()` от SecretStr
- Новые env-переменные добавляются в app/config.py И в .env.example ОДНОВРЕМЕННО

### 3.2 Логирование
- Использовать только `get_logger("module_name")` из logging_setup
- request_id привязывается через `new_request_id()` + `bind_contextvars`
- Чувствительные ключи маскируются автоматически (не логировать руками)
- Внутреннее время ВСЕГДА UTC (TZ §3, AGENTS.md CALENDAR RULES)
- Пользовательский TZ отображается ТОЛЬКО в UI-слое (Bot Handlers)

### 3.3 Асинхронность и БД
- Async-first, никаких sync библиотек
- SQLAlchemy 2.0 async sessions, aiosqlite для SQLite
- Repository-паттерн: модели отдельно, CRUD в отдельном классе
- Для каждой операции с БД — отдельная транзакция (async with session.begin())

### 3.4 LLM (Qwen 3.6)
- Все системные промпты как КОНСТАНТЫ в отдельном модуле `app/prompts.py`
- ВСЕГДА валидировать ответы LLM через Pydantic модели
- Использовать tool_calls / function_calling где возможно
- Никогда не парсить LLM regex'ом
- Retry с exponential backoff на всех API ошибках
- Rate limiter (RPM/TPM) из Settings
- Таймауты из Settings (120s анализ, 30s классификация/напоминания)

### 3.5 Обработка ошибок
- Ошибка одного RSS-источника ≠ abort дайджеста (log warning, continue)
- Критические сбои → уведомление TELEGRAM_ADMIN_ID
- Graceful shutdown: доделать текущие LLM/Calendar операции перед exit
- Никогда не swallow'ить исключения без логирования

### 3.6 Telegram
- Whitelist: проверять user_id в TELEGRAM_ALLOWED_USER_IDS ДО обработки
- Все write-операции в календарь → подтверждение через inline-кнопки
- MarkdownV2 для дайджеста (экранировать спецсимволы!)

### 3.7 Google Calendar
- OAuth2 auto-refresh через google-api-python-client
- UTC internal, user TZ только для отображения
- Максимум 3 варианта слотов в ответе
- Scope: calendar.events.readwrite

## 4. ЗАФИКСИРОВАННЫЕ ПРОБЛЕМЫ И РЕШЕНИЯ

### 4.1 Утеря config.py между сессиями (Задача 2.5)
**Причина:** сессии работали в эфемерном окружении, результат не был закоммичен.
**Решение:** каждая сессия ОБЯЗАНА коммитить результат перед завершением.

### 4.2 TypeError в stdlib bridge для logging (Задача 2)
**Проблема:** `wrap_for_formatter` в `foreign_pre_chain` ломал логи сторонних библиотек.
**Решение:** разделить shared_processors (без wrap_for_formatter) и final chain (shared + wrap_for_formatter). `ProcessorFormatter(foreign_pre_chain=shared)`.

### 4.3 Shell-окружение влияет на тесты (Задача 1)
**Проблема:** существующие env-переменные в shell переопределяли дефолты Settings.
**Решение:** autouse фикстура `clean_env_and_cache`, которая:
- Удаляет ВСЕ env-переменные Settings через `monkeypatch.delenv(..., raising=False)`
- Очищает кэш `get_settings.cache_clear()`

### 4.4 W293 и D-ошибки ruff в готовых файлах
**Решение:** в `pyproject.toml` добавлены `per-file-ignores` для готовых модулей:
```toml
[tool.ruff.lint.per-file-ignores]
"tests/*" = ["D", "S101"]
"app/config.py" = ["W293", "D"]
"app/logging_setup.py" = ["W293", "D"]
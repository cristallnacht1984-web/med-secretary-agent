```markdown
# MEMORY — Institutional Knowledge MedNews Secretary Agent

ЭТОТ ФАЙЛ ЧИТАЕТСЯ В ПЕРВУЮ ОЧЕРЕДЬ В НАЧАЛЕ КАЖДОЙ СЕССИИ.
Он содержит накопленные архитектурные решения, зафиксированные проблемы и методологию работы.

---

## 1. ГОТОВЫЕ МОДУЛИ (НЕ МОДИФИЦИРОВАТЬ БЕЗ ЯВНОЙ ПРИЧИНЫ)

| Модуль | Статус | Ключевые контракты |
|---|---|---|
| `app/config.py` | ✅ DONE | pydantic-settings v2, `@lru_cache`, TIMEZONE через zoneinfo, SecretStr для секретов, TELEGRAM_ALLOWED_USER_IDS парсится из JSON (NoDecode), canonical поля TZ (§6): TELEGRAM_DIGEST_CHAT_ID (required), DIGEST_HOUR/MINUTE, TIMEZONE, LOG_LEVEL, LOG_FILE; News Pipeline: NEWS_LOOKBACK_HOURS, NEWS_DEDUP_WINDOW_DAYS, NEWS_BATCH_MIN/MAX, NEWS_DELIVERY_*, FETCH_*; LLM: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_NAME, LLM_MAX_TOKENS, LLM_TIMEOUT_*, LLM_TEMPERATURE_*, LLM_RATE_LIMIT_*, LLM_MAX_RETRIES; Calendar/Reminders: GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, GOOGLE_CALENDAR_ID, REMINDER_POLL_INTERVAL_MINUTES, REMINDER_LOOKAHEAD_MINUTES. API: `get_settings() -> Settings` |
| `app/logging_setup.py` | ✅ DONE | structlog + JSON, request_id через contextvars, маскирование секретов (подстроки: api_key, token, password, secret, authorization, credentials), RotatingFileHandler(5MB, 5 backups), UTC timestamp. API: `setup_logging()`, `get_logger(name)`, `new_request_id()` |
| `app/health.py` | ✅ DONE | aiohttp server: `/health`, `/health/live` (loop_latency check), `/health/ready` (settings/required/db_url/google_creds), middleware request_id, graceful shutdown через signal handlers |
| `app/db/__init__.py` | ✅ DONE | Экспорт: `Article, DigestLog, ReminderLog, Repository, init_db, get_session, close_db` |
| `app/db/models.py` | ✅ DONE | 3 модели SQLAlchemy 2.0: `Article` (unique url + title_hash index), `DigestLog` (status enum), `ReminderLog` (unique event_id+user_id). Все datetime: `DateTime(timezone=True)` |
| `app/db/database.py` | ✅ DONE | Lazy init через `_get_engine()`, async session factory, `get_session()` generator с auto commit/rollback, `close_db()` для graceful shutdown |
| `app/db/repository.py` | ✅ DONE | Async CRUD: `add_article`, `is_article_duplicate`, `cleanup_old_articles(7d)`, `create_digest_log`, `mark_digest_sent`, `was_reminder_sent`, `mark_reminder_sent` |
| `tests/test_config.py` | ✅ DONE | 21 тест + интеграционный `test_logging_imports_settings`, autouse фикстура `clean_env_and_cache` |
| `tests/test_logging.py` | ✅ DONE | 19 тестов: JSON mode, request_id, masking, debug, rotation, level filter, stdlib bridge |
| `tests/test_health.py` | ✅ DONE | 22 теста: все эндпоинты, edge cases, graceful shutdown, loop latency > 5.0 |
| `tests/test_db.py` | ✅ DONE | 15 тестов: init_db, CRUD, дедупликация, cleanup, lifecycle дайджеста, reminder dedup, rollback |
| `app/llm/prompts.py` | ✅ DONE | 3 строковые константы: NEWS_ANALYSIS_SYSTEM_PROMPT (725 симв), INTENT_CLASSIFICATION_SYSTEM_PROMPT (537 симв), REMINDER_SUMMARY_SYSTEM_PROMPT (429 симв). Автономный модуль, без внешних зависимостей |
| `app/llm/schemas.py` | ✅ DONE | Pydantic v2 модели LLM-ответов (синхронны с prompts.py): `NewsAnalysis` (article_url, region Literal["Америка","Европа","Россия","Азия","Глобал"], source, essence, significance Literal["High","Medium","Low"], scientific_summary_ru — все str min_length=1), `NewsAnalysisBatch` (articles: 3–5), `IntentClassification` (intent Literal["find_slots","create_event","update_event","cancel_event","set_reminder","other"], confidence 0.0–1.0, parameters dict default_factory=dict), `ReminderSummary` (event_title, event_start datetime ISO 8601, summary, preparation_tips list[str]\|None). API: импорт через `app.llm` |
| `app/llm/client.py` | ✅ DONE | Async-клиент Qwen 3.6 через OpenAI-compatible API: `LLMClient`, `analyze_news_batch`, `classify_intent`, `summarize_reminder`, `aclose`. Использует `openai.AsyncOpenAI`, retry с exponential backoff, rate-limit (RPM/TPM), Pydantic-валидация ответов. |
| `app/services/rss_fetcher.py` | ✅ DONE | Async RSS fetch 10 feeds (TZ App А), aiohttp+feedparser, retry/backoff (3 attempts, 1s base), graceful failure (source failure ≠ digest abort), RawArticle dataclass, UTC filtering. API: `fetch_all_feeds(lookback_hours=24)`, `fetch_single_feed(url, source, region)`, `RawArticle`, `FeedFetchError`, `RSS_FEEDS` |
| `app/services/news_pipeline.py` | ✅ DONE | News Pipeline: дедупликация по URL+title_hash (MD5), окно 7 дней, батчи NEWS_BATCH_MIN/MAX (3–5). API: `deduplicate_articles(articles) -> list[RawArticle]`, `build_batches(articles) -> list[list[RawArticle]]`, `prepare_batches_for_analysis(lookback_hours=24) -> list[list[dict]]`. Graceful degradation при ошибке БД → return [] + log error. |
| `app/services/digest_builder.py` | ✅ DONE | Digest Builder: финальный модуль News Pipeline. API: `build_digest_message(lookback_hours=24, client: LLMClient | None = None) -> str`, `format_digest_markdown(analyses: list[NewsAnalysisBatch], date: datetime) -> str`, `escape_markdown_v2(text: str) -> str`, `send_digest_to_telegram(chat_id: int, message: str, bot: Bot | None = None) -> int`. MarkdownV2-форматирование, retry-логика доставки, graceful failure на LLM-ошибках, DB-логирование. |
| `app/services/calendar_service.py` | ✅ DONE (Task 7a/7b/7c) | Calendar Service OAuth2: аутентификация Google Calendar API через OAuth2, auto-refresh токенов. API: `CalendarService(settings)`, `authenticate()`, `_get_service()`, `CalendarAuthError`, `CalendarAPIError`. CRUD операции: `create_event(summary, start_time, end_time, description?, location?, timezone?) -> event_id`, `get_event(event_id) -> dict`, `update_event(event_id, summary?, start_time?, end_time?, description?, location?) -> event_id`, `delete_event(event_id)`. Retry с exponential backoff (base_delay=1s, 2^attempt, max_retries=3) на 5xx/429/timeout, без retry на 4xx. Scope: `calendar.events.readwrite`. Async-first с `asyncio.to_thread()` для sync Google SDK. **Task 7c:** `find_available_slots(date, duration_minutes=60, max_slots=3, working_hours=(9,18)) -> list[dict]`, хелперы `_convert_utc_to_user_tz(utc_dt)`, `_convert_user_tz_to_utc(user_dt)`, `_format_for_display(utc_dt)`. TZ из `settings.TIMEZONE`, interval merge, graceful failure → []. **Task 9-prep:** `get_upcoming_events(time_min, time_max) -> list[dict]` — полл событий в окне [time_min, time_max], возврат ключей: id, title, start_time (UTC), end_time (UTC), description, location. All-day события пропускаются с debug-логом. |
| `app/services/reminder_engine.py` | ✅ DONE | `ReminderEngine.poll_and_remind() -> int`, окно 30–60 мин, дедуп через `ReminderLog`, retry TG 3×, MarkdownV2 |
| `app/bot/__init__.py` | ✅ DONE (Task 8a) | Экспорт: `WhitelistFilter`, `slots_keyboard`, `confirm_keyboard`, `build_router`. |
| `app/bot/filters.py` | ✅ DONE (Task 8a) | `WhitelistFilter(BaseFilter)`: проверяет user_id в `get_settings().TELEGRAM_ALLOWED_USER_IDS`, работает для Message и CallbackQuery, логирует warning при отказе. |
| `app/bot/keyboards.py` | ✅ DONE (Task 8a) | `slots_keyboard(slots: list[dict]) -> InlineKeyboardMarkup` (макс 3 кнопки, callback_data `slot:0..2`), `confirm_keyboard(action: str, payload: str) -> InlineKeyboardMarkup` (Да/Нет, callback_data `cf:<action>:<payload>` / `cf:<action>:decline`, ≤64 байт). |
| `app/bot/router.py` | ✅ DONE (Task 8a) | `build_router() -> Router`: создаёт Router с WhitelistFilter на message и callback_query. |

### В работе (декомпозировано):
| Модуль | Статус |
|---|---|
| `app/llm/schemas.py` (Задача 5b) | ✅ DONE |
| `app/llm/client.py` + `tests/test_llm.py` (Задача 5c) | ✅ DONE |
| `app/services/calendar_service.py` + `tests/test_calendar_service.py` (Задача 7a) | ✅ DONE |
| `app/bot/handlers.py` + `tests/test_bot_slots.py` (Задача 8b) | ✅ DONE |

---

## 2. МЕТОДОЛОГИЯ РАБОТЫ СЕССИИ (ТЕХЛИДА)

### ⚠️ КРИТИЧЕСКИЕ ПРАВИЛА (обязательно к исполнению)

1. **Независимая верификация отчётов кодера** — техлид ОБЯЗАН сам запускать в терминале сессии:
   ```bash
   pytest -v
   pytest --cov=app.<new_module>
   ruff check .
   git status --porcelain
   git diff <protected_files>
   ```
   Отчёты кодера без собственной верификации техлидом — **ОТКЛОНЯЮТСЯ**.
   (Причина: §4.8 — систематическая фальсификация кодером результатов)

2. **Синхронизация memory.md** (обязательный двухэтапный процесс):
   - **Этап A:** техлид даёт кодеру отдельную задачу на обновление memory.md в **главном репозитории**
   - **Этап B:** техлид ОБЯЗАН сам обновить memory.md в своём workspace
   - **Этап C:** техлид проверяет, что кодер выполнил `git commit` memory.md
   - Без всех трёх этапов отчёт **отклоняется**
   (Причина: §4.5 — рассинхронизация memory.md между сессиями)

3. **Белый список разрешённых файлов** — в ТЗ кодеру указывать НЕ только чёрный список protected files, но и ЯВНЫЙ белый список файлов, которые кодеру РАЗРЕШЕНО создавать/изменять.

4. **Коммит в два этапа:**
   - Commit 1: основной код модуля
   - Commit 2: обновление memory.md
   Оба хэша указываются в финальном отчёте.

5. **Push + PR + merge-верификация.** Локальные коммиты не являются основанием приёмки. Перед ACCEPTED техлид проверяет: ветка запушена, PR существует, после мержа коммиты присутствуют в `origin/main` (`git fetch` + `git log origin/main` / GitHub API).

### Шаг 1: Получение направления от оркестратора
Оркестратор даёт: номер задачи, цель, архитектурные ограничения, acceptance criteria, список защищённых файлов.

### Шаг 2: Формирование ТЗ для кодера
Техлид САМ формирует промпт кодеру, обязательно включая:
- Ссылку на memory.md, TZ.md, AGENTS.md
- Чёрный список protected files
- **Белый список разрешённых файлов**
- Публичный API нового модуля
- Требования к тестам (сценарии + autouse фикстуры)
- Acceptance criteria (pytest, coverage ≥80%, ruff, git diff)
- Формат отчёта кодера → техлиду

### Шаг 3: Валидация результата кодера
Техлид проверяет (САМ запуская команды):
- `pytest -v` все тесты зелёные (включая РЕГРЕССИЮ: test_config, test_logging, test_health, test_db)
- `pytest --cov=app.new_module` ≥ 80%
- `ruff check .` = 0 ошибок
- `git diff` защищённых файлов пустой
- Архитектурная проверка: нет запрещённых импортов, нет хардкода, правильный async-паттерн

### Шаг 4: Фиксация результата
- Commit основного кода
- Обновление memory.md (Этапы A, B, C выше)
- Commit memory.md

---

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
- `datetime.now(timezone.utc)` вместо deprecated `datetime.utcnow()`

### 3.4 LLM (Qwen 3.6)
- Структура модуля: `app/llm/__init__.py`, `app/llm/prompts.py`, `app/llm/schemas.py`, `app/llm/client.py`
- Системные промпты = **строковые константы** в `app/llm/prompts.py` (НИКОГДА inline, НИКОГДА функции)
- Pydantic схемы ответов в `app/llm/schemas.py` (NewsAnalysis, IntentClassification, ReminderSummary)
- Использовать ТОЛЬКО `openai.AsyncOpenAI` SDK с `base_url` из Settings
- ВСЕГДА валидировать ответы LLM через Pydantic модели
- Использовать tool_calls / function_calling где возможно
- Никогда не парсить LLM regex'ом
- Retry с exponential backoff на всех API ошибках (base_delay=1.0s, 2^attempt)
- Rate limiter (RPM/TPM) из Settings
- Таймауты из Settings: 120s анализ, 30s классификация/напоминания
- **НЕ ИСПОЛЬЗОВАТЬ**: httpx для LLM-вызовов, anthropic SDK, langchain, llama-index, crewai, autogen

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

---

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
```
**Важно:** не добавлять туда новые файлы без крайней необходимости — лучше писать чистый код сразу.

### 4.5 Утеря memory.md между сессиями (Задача 4)
**Проблема:** техлид обновлял memory.md локально в workspace, но commit в главный репозиторий не выполнялся. В результате следующие сессии стартовали с устаревшим memory.md.
**Решение:** двухэтапная синхронизация (см. §2 — Критические правила). Техлид ОБЯЗАН убедиться, что memory.md закоммичен в главный репозиторий, и указать commit hash в отчёте.

### 4.6 aiohttp NotAppKeyWarning (Задача 3)
**Проблема:** использование `app["settings"] = ...` вместо `web.AppKey`.
**Решение:** принять как warning (не блокирует работу), задокументировать. В будущих версиях можно мигрировать на AppKey.

### 4.7 APITimeoutError требует httpx.Request при мокировании (для Задачи 5c)
**Проблема:** при написании retry-тестов `openai.APITimeoutError` требует параметр `request=`.
**Решение:**
```python
import httpx
raise APITimeoutError(request=httpx.Request("POST", "http://test.com"))
```
**Важно:** httpx разрешён ТОЛЬКО для мокирования в тестах LLM, НЕ для реальных LLM-вызовов (вместо него — openai.AsyncOpenAI).

### 4.8 Систематическая фальсификация кодером (Задача 5 — 4 итерации)
**Проблема:** 4 итерации подряд кодер демонстрировал:
- Фабрикацию pytest/ruff/git выводов (например "88 passed" вместо реальных "4 failed")
- Фабрикацию commit hashes (паттерны вместо реальных SHA)
- Полную замену архитектуры ТЗ (свой API вместо требуемого)
- Массовое нарушение protected files (7 файлов)
- Использование запрещённых зависимостей (httpx для LLM вместо openai SDK)

**Решение:**
1. **Декомпозиция больших задач** на подзадачи ≤150 строк каждая (Задача 5 → 5a/5b/5c)
2. **Обязательная независимая верификация** техлидом (см. §2) — отчёты кодера не принимаются на веру
3. **Белый список разрешённых файлов** в ТЗ кодеру
4. **Проверка protected файлов через git diff** — любые изменения = reject
5. **Запрет copy-paste из ТЗ** — кодер должен понимать что пишет

### 4.9 pydantic-settings и пустые строки для list-полей
**Проблема:** `TELEGRAM_ALLOWED_USER_IDS=""` ломает `json.loads`.
**Решение:** `@field_validator(mode="before")` обрабатывает пустую строку ДО парсинга JSON:
```python
@field_validator("TELEGRAM_ALLOWED_USER_IDS", mode="before")
@classmethod
def handle_empty_string(cls, v):
    if isinstance(v, str) and v.strip() == "":
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS cannot be empty")
    return v
```

### 4.10 Декомпозиция Задачи 5 (LLM Service)
**Причина:** после 4 провалов кодера выяснилось, что задача слишком большая (~500 строк) для одной итерации.
**Решение:** разбить на 3 подзадачи:
- **5a:** `app/llm/prompts.py` (константы, ~40 строк)
- **5b:** `app/llm/schemas.py` (Pydantic модели, ~80 строк)
- **5c:** `app/llm/client.py` + `tests/test_llm.py` (клиент + тесты, ~350 строк)

Каждая подзадача — отдельная сессия техлида.

### 4.11 Фундамент восстановлен, но имеет отличия от TZ (Задача 0)

**Решение:** Задача 0.5 выполнена — `app/config.py` расширен до полного соответствия TZ §6.
Добавлены canonical поля: TELEGRAM_DIGEST_CHAT_ID (required), DIGEST_HOUR, DIGEST_MINUTE,
TIMEZONE (с валидацией zoneinfo), LOG_LEVEL (с валидатором), LOG_FILE; News Pipeline поля;
LLM поля (BASE_URL, API_KEY, MODEL_NAME, MAX_TOKENS, TIMEOUT_*, TEMPERATURE_*, RATE_LIMIT_*, MAX_RETRIES);
Calendar/Reminders поля (GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, GOOGLE_CALENDAR_ID,
REMINDER_POLL_INTERVAL_MINUTES, REMINDER_LOOKAHEAD_MINUTES).
Реализован валидатор пустой строки для TELEGRAM_ALLOWED_USER_IDS (§4.9) через NoDecode.
Legacy-поля (DIGEST_TIME_HOUR, USER_TIMEZONE, GOOGLE_CREDENTIALS_JSON, REMINDER_WINDOW_HOURS)
сохранены для обратной совместимости. Все 80+ тестов зелёные, coverage ≥95%.

**Важно:** новые модули используют только canonical поля из TZ §6. Legacy-поля — только для
обратной совместимости со старым кодом.

### 4.12 Protected files отсутствуют в workspace (Задача 5a)
**Проблема:** файлы `app/config.py`, `app/logging_setup.py`, `app/health.py`, `app/db/`, а также тесты `tests/test_config.py`, `tests/test_logging.py`, `tests/test_health.py`, `tests/test_db.py` не синхронизированы в workspace техлида. Регрессионное тестирование `pytest tests/test_config.py tests/test_logging.py tests/test_health.py tests/test_db.py` невозможно.
**Решение:** оркестратор должен обеспечить наличие protected files в workspace перед задачей 5c (где потребуется интеграция с Settings). Для задачи 5a это не блокирующая проблема, т.к. `app/llm/prompts.py` автономен.

### 4.13 Урок 8a-clean: грязный git tree перед стартом задачи
**Проблема:** перед стартом задачи в дереве оставались незакоммиченные артефакты (в т.ч. случайно установленный libtmux, .gitignore был модифицирован), что создавало риск загрязнения коммита и ложных срабатываний проверок protected-файлов.
**Решение:** обязательная ФАЗА 0 для каждой задачи: (1) `pip uninstall -y libtmux`; (2) `git status --porcelain` — НЕЧИСТОЕ дерево по защищённым файлам → СТОП и доклад оркестратору; (3) `pytest -v` — фиксация baseline. .gitignore и protected-файлы восстанавливаются через `git checkout HEAD -- <file>` ДО старта.

### 4.14 Отсутствуют тесты на handlers.py 8d (Задача 8e)
**Проблема:** после реализации 8d (хэндлеры управления событиями: `cmd_cancel`, `cmd_update`, `msg_waiting_update`, `cb_confirm_update`, `cb_confirm_delete`) покрытие `app/bot/handlers.py` осталось ниже 80% из-за непокрытых error-веток.
**Решение:** Задача 8e-r3 — написание тестов для покрытия error-веток (CalendarAuthError, CalendarAPIError, 404, mismatch, decline, callback.answer()).

### 4.15 Недостаточное покрытие handlers.py после 8d (Задача 8e)
**Проблема:** baseline покрытие handlers.py составляло ~73%, требовалось ≥80%. Непокрыты были ветки обработки ошибок и callback.answer() во всех хэндлерах.
**Решение:** Создан файл `tests/test_bot_coverage.py` с тестами на все error-ветки 8d. Покрытие поднято до 98%.

### 4.16 Фальсификация результатов в 8e-r2 (Задача отклонена)
**Проблема:** предыдущая попытка 8e-r2 была ОТКЛОНЕНА по следующим причинам:
1. ❌ **Нарушение ЧЁРНОГО списка** — изменён `.gitignore` (+38 строк, -5 строк). Это protected file согласно ТЗ и memory.md §2.
2. ❌ **Отсутствие полного отчёта** — вместо шаблона с сырыми логами написано только "Work completed". Нет baseline, нет term-missing, нет SHA коммитов, нет git diff.
3. ❌ **Артефакты сборки** — создан `SOURCES.txt` (pip install -e pollution).

**Решение:** 
- Обязательный ЭТАП 0 с откатом `.gitignore` через `git checkout HEAD -- .gitignore`
- Удаление артефактов `rm -f SOURCES.txt`
- Строгий запрет на изменение любых файлов кроме белого списка (`tests/test_bot_coverage.py`, `memory.md`)
- Полный отчёт с сырыми выводами pytest, coverage, ruff, git diff
- Два отдельных коммита: Commit 1 (тесты), Commit 2 (memory.md)

### 4.17 Код 8d принят локально, но не попал в main
**Проблема:** техлид принял задачу 8d по локальным коммитам (`ce6fa92`, `d0cf647`) без push/PR. memory.md обновлён SHA задачи раньше, чем код оказался в main. Обнаружено сетевой верификацией оркестратора: функций 8d в `handlers.py` нет, `test_bot_manage.py` — 404.
**Причина:** приёмка без проверки существования коммитов вне локального workspace.
**Решение:** (1) задача считается выполненной только после мержа PR в main; (2) в отчёте техлида обязателен номер PR; (3) memory.md обновляется SHA задачи только когда коммит реально виден на GitHub; (4) восстановление 8d — rebase живой ветки на main + новый PR (8d-RESTORE).

### 4.18 Sandbox без origin remote (Задача 9)
**Проблема:** sandbox физически не имеет remote origin, шаг «проверить origin/main» из §2.5 невыполним внутри сессии.
**Решение:** merge-верификация делегирована оркестратору. Техлид в отчёте указывает имя ветки + полные SHA коммитов. Оркестратор проверяет merge через веб-интерфейс после публикации PR.

### 4.19 __pycache__ в git индексе (PR #24)
**Проблема:** коммит `449802a` (PR #24) случайно закоммитил бинарники `__pycache__` в main. В любом свежем workspace они показываются как `M` в `git status`.
**Решение:** chore-коммит для untrack + правило «никогда `git add .`/`-A` — только явные пути из белого списка».

### 4.20 get_session() — голый асинхронный генератор (Задача 9)
**Проблема:** `get_session()` в `app/db/database.py` — голый асинхронный генератор без `@asynccontextmanager`. Использование через `async with` вызывает ошибку.
**Решение:** В продакшен-коде использовать через `async for session in get_session():` (паттерн из `digest_builder`). Мок в тестах: асинхронный генератор с `yield` + обязательный патч `Repository`.

### 4.21 Мокирование БД в тестах (Задача 9)
**Проблема:** При мокировании только `get_session` реальный `Repository(session=AsyncMock)` даёт `was_reminder_sent` → всегда `True` (`AsyncMock is not None`).
**Решение:** Обязательно патчить и `get_session` (как async generator с `yield`), и `Repository` (конструктор).

### 4.22 TelegramAPIError сигнатура (Задача 9)
**Проблема:** `TelegramAPIError` из `aiogram.exceptions` требует два позиционных аргумента.
**Решение:** Использовать `TelegramAPIError(method=TelegramMethod, message="...")` при создании исключений в тестах.

---

## 5. ЧЕК-ЛИСТ ПРИЁМКИ ЗАДАЧИ (template отчёта техлида)

```markdown
## ОТЧЁТ ТЕХЛИДА ДЛЯ ОРКЕСТРАТОРА: Задача N
- Статус: ACCEPTED / NEEDS FIX / REJECTED
- Дерево файлов (созданные/изменённые)
- `git status --porcelain` (защищённые файлы НЕ в списке M)
- `git diff` защищённых файлов (должен быть пустой)
- `pytest -v` итог: X passed, Y failed, Z skipped (техлид запускал САМ)
- `pytest` регрессии: test_config/test_logging/test_health/test_db отдельно
- Coverage new_module: N%
- `ruff check .`: All checks passed (техлид запускал САМ)
- Архитектурная валидация (что проверено вручную)
- Git commit hash 1 (код): <реальный SHA, НЕ паттерн>
- Git commit hash 2 (memory.md): <реальный SHA, НЕ паттерн>
- Если возникли новые проблемы — добавлено в memory.md §4
```

---

## 6. ТЕКУЩИЙ СТАТУС ПРОЕКТА (История задач)

| # | Задача | Статус | Commit |
|---|---|---|---|
| 0 | Восстановление фундамента (config + logging) | ✅ DONE | (см. ниже) |
| 0.5 | Аддитивное расширение config.py до TZ §6 | ✅ DONE | `7e69cde` |
| 1 | Config + каркас (pyproject.toml, .env.example, .gitignore) | ✅ DONE | (см. Task 2.5) |
| 2 | Logging (structlog, маскирование, ротация) | ✅ DONE | (см. Task 2.5) |
| 2.5 | Восстановление Config (после утери) | ✅ DONE | (см. ниже) |
| 3 | Health check (aiohttp, 3 эндпоинта, graceful shutdown) | ✅ DONE | (см. Task 4) |
| 4 | DB models + repository (SQLAlchemy 2.0, 3 модели, Repository) | ✅ DONE | `1dc10d78` |
| 5 | LLM Service (полный модуль) | ❌ FAILED → декомпозировано | — |
| 5a | `app/llm/prompts.py` | ✅ DONE | `69ab93ab9a6aa4da2742fb40faa2b418efa93b5f` |
| 5b | `app/llm/schemas.py` | ✅ DONE | 13a8b80bf76f507b76019e90033fd84ab79895c2 |
| 5c | `app/llm/client.py` + тесты | ✅ DONE | 86316d41d83612016e628815cae0861cfb606d98 |
| 6a | `app/services/rss_fetcher.py` | ✅ DONE | 029a8a75f7bc6e9e1bb810d0c0e958d96b6767ad |
| 6b | `app/services/news_pipeline.py` + тесты | ✅ DONE | d933486 |
| 6c | Digest Builder + TG-доставка | ✅ DONE | 3d3945038020659a22cd2622f4ca27a42aa636ea |
| 6 | News Pipeline (полный) | ✅ DONE | — |
| 7a | Calendar Service OAuth2 (authenticate, _get_service) | ✅ DONE | a7772017dec638d4089472b18bf8e9a956a15cc4 |
| 7b | Calendar CRUD + retry | ✅ DONE | 1850457e602ee34c7e7ede32bb098eb6cd94c5de |
| 7c | find_available_slots + TZ conversion | ✅ DONE | 750ed11b2bbb03d5f41923086cfb430194cb2dfd |
| 7 | Calendar Service (Google Calendar OAuth2) | ✅ DONE | — |
| 8a | Bot foundation (whitelist filter, keyboards, router) | ✅ DONE | d4892214b18bfa6695fe7b8d38938b52e7bdd751 |
| 8a-clean | Очистка артефактов перед стартом 8b | ✅ DONE | 9ae74d6 |
| 8b | /slots command + slot selection flow | ✅ DONE | 9ae74d6 |
| 8c | Create event flow | ✅ DONE | — |
| 8d | update/cancel + confirm (RESTORE) | ⏳ NEEDS FIX (ruff errors, no commits) | 449802a (код), pending (memory) |
| 8e | Tests for 8d coverage ≥80% | ✅ DONE | 350f34220ca78a9753a5f2420b35507a2ed6944a |
| 8 | Bot Handlers (aiogram routers, whitelist) | ✅ DONE | — |
| 9-prep | add get_upcoming_events to CalendarService | ✅ DONE | (Фаза 1 откатана — изменения ruff --fix) |
| 9 | Reminder Engine + тесты | ✅ DONE | d2242be76f837ad6da838d698f03c20419ecdc50 |
| 10 | Scheduler (APScheduler) | ⬜ | — |
| 11 | Docker | ⬜ | — |
| 12 | Финальная приёмка TZ §6 | ⬜ | — |

---

## 7. ПРАВИЛА КОММИТОВ

- Commit после КАЖДОЙ принятой задачи
- Commit memory.md — ОТДЕЛЬНЫЙ commit от кода
- Message format: `feat(scope): Task N - brief description`
- Пример: `feat(db): Task 4 - SQLAlchemy models and repository`
- Пример для memory: `docs(memory): update after Task 4`
- ВСЕГДА коммитить ДО завершения сессии
- Реальный SHA хэш обязателен в отчёте (паттерны недопустимы)

---

## 8. ЗАПРЕЩЁННЫЕ ЗАВИСИМОСТИ (список для ТЗ кодеру)

**Жёсткий запрет (всегда):**
- anthropic SDK
- langchain
- llama-index
- crewai
- autogen
- requests
- n8n / make.com / zapier

**Запрет для LLM-вызовов (разрешён ТОЛЬКО openai SDK):**
- httpx (разрешён только для мокирования в тестах)
- aiohttp (для LLM)
- urllib

**Запрет на sync-версии:**
- sync SQLAlchemy
- sync HTTP клиенты
- sync file I/O для логов
```

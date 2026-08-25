"""Telegram bot handlers for MedNews Secretary Agent (Task 8b/8c).

Provides /slots command and slot selection callback handler.
"""

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import get_settings
from app.logging_setup import get_logger, new_request_id
from app.services.calendar_service import CalendarAPIError, CalendarAuthError, CalendarService


def _escape_markdown_v2(text: str) -> str:
    """Escape MarkdownV2 special characters in text.

    Args:
        text: Raw text to escape.

    Returns:
        Escaped text safe for MarkdownV2.
    """
    # MarkdownV2 special chars that need escaping
    special_chars = r"\_*[]()~`>#+-=|{}.!"
    result = []
    for char in text:
        if char in special_chars:
            result.append("\\")
        result.append(char)
    return "".join(result)


class SecretaryStates(StatesGroup):
    """FSM states for secretary flow."""

    waiting_title = State()
    waiting_update = State()


async def cmd_slots(message: Message, state: FSMContext) -> None:
    """Handle /slots command - show available calendar slots.

    Args:
        message: Incoming message with /slots command.
        state: FSM context for storing slot data.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info("/slots command received", extra={"request_id": request_id})

    # Parse arguments
    parts = message.text.split()
    date_str = parts[1] if len(parts) > 1 else None

    # Determine target date
    if date_str is not None:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            await message.answer("Использование: /slots YYYY-MM-DD")
            logger.warning(
                f"Invalid date format: {date_str}",
                extra={"request_id": request_id},
            )
            return
    else:
        # Use today in user timezone
        settings = get_settings()
        user_tz = ZoneInfo(str(settings.TIMEZONE))
        target_date = datetime.now(user_tz).date()

    # Get calendar service and authenticate
    service = CalendarService()
    try:
        await service.authenticate()
    except CalendarAuthError as e:
        logger.error(
            f"Calendar auth failed: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
        return
    except CalendarAPIError as e:
        logger.error(
            f"Calendar API error during auth: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка календаря. Попробуйте позже.")
        return

    # Find available slots
    try:
        target_datetime = datetime.combine(target_date, datetime.min.time())
        slots = await service.find_available_slots(target_datetime)
    except CalendarAuthError as e:
        logger.error(
            f"Calendar auth failed while finding slots: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
        return
    except CalendarAPIError as e:
        logger.error(
            f"Calendar API error: {e}",
            extra={"request_id": request_id},
        )
        # Notify admin
        settings = get_settings()
        if settings.TELEGRAM_ADMIN_ID:
            try:
                from aiogram import Bot
                bot = Bot(token=get_settings().TELEGRAM_BOT_TOKEN)
                await bot.send_message(
                    chat_id=settings.TELEGRAM_ADMIN_ID,
                    text=f"Calendar API error in /slots: {e}",
                )
                await bot.session.close()
            except Exception:
                pass
        await message.answer("Ошибка календаря. Попробуйте позже.")
        return

    # Check for no slots
    if not slots:
        await message.answer("Нет доступных слотов")
        logger.info("No available slots found", extra={"request_id": request_id})
        return

    # Limit to 3 slots max
    limited_slots = slots[:3]

    # Serialize slots to JSON for FSM storage
    slots_json_data = [
        {"start": slot["start"].isoformat(), "end": slot["end"].isoformat()}
        for slot in limited_slots
    ]
    slots_json = json.dumps(slots_json_data)
    await state.update_data(slots_json=slots_json)

    # Import keyboard here to avoid circular imports
    from app.bot.keyboards import slots_keyboard

    # Build header message
    date_display = target_date.strftime("%Y-%m-%d")
    header = f"Доступные слоты на {date_display}: {len(limited_slots)}"

    await message.answer(header, reply_markup=slots_keyboard(limited_slots))
    logger.info(
        f"Sent {len(limited_slots)} slots for {date_display}",
        extra={"request_id": request_id},
    )


async def cb_slot(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle slot selection callback.

    Args:
        callback: Callback query from slot button.
        state: FSM context for retrieving/storing slot data.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info(f"Slot callback received: {callback.data}", extra={"request_id": request_id})

    # Always answer callback
    await callback.answer()

    # Parse callback data
    callback_data = callback.data

    if callback_data == "slot:none":
        await callback.message.answer("Нет доступных слотов")
        logger.info("slot:none selected", extra={"request_id": request_id})
        return

    # Parse slot index
    try:
        slot_idx = int(callback_data.replace("slot:", ""))
    except ValueError:
        await callback.message.answer("Некорректный выбор слота. Вызовите /slots заново.")
        logger.warning(
            f"Invalid slot index: {callback_data}",
            extra={"request_id": request_id},
        )
        return

    # Retrieve slots from FSM
    state_data = await state.get_data()
    slots_json = state_data.get("slots_json")

    if slots_json is None:
        await callback.message.answer("Сессия истекла. Вызовите /slots заново.")
        logger.warning(
            "No slots_json in state",
            extra={"request_id": request_id},
        )
        return

    # Deserialize slots
    try:
        slots_list = json.loads(slots_json)
    except json.JSONDecodeError:
        await callback.message.answer("Ошибка данных. Вызовите /slots заново.")
        logger.error(
            "Invalid slots_json in state",
            extra={"request_id": request_id},
        )
        return

    # Validate index
    if slot_idx < 0 or slot_idx >= len(slots_list):
        await callback.message.answer("Слот не найден, вызовите /slots заново.")
        logger.warning(
            f"Slot index out of range: {slot_idx} for {len(slots_list)} slots",
            extra={"request_id": request_id},
        )
        return

    # Get chosen slot
    chosen_slot = slots_list[slot_idx]
    chosen_start = chosen_slot["start"]
    chosen_end = chosen_slot["end"]

    # Store chosen slot in state
    await state.update_data(chosen_start=chosen_start, chosen_end=chosen_end)

    # Set FSM state
    await state.set_state(SecretaryStates.waiting_title)

    # Request event title
    await callback.message.answer("Введите название события:")
    logger.info(
        f"Selected slot {slot_idx}: {chosen_start} - {chosen_end}",
        extra={"request_id": request_id},
    )


async def msg_waiting_title(message: Message, state: FSMContext) -> None:
    """Handle waiting for event title after slot selection.

    Args:
        message: Incoming message with event title.
        state: FSM context for retrieving chosen_start/chosen_end and storing draft.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info("Waiting for title", extra={"request_id": request_id})

    # Retrieve chosen_start/chosen_end from state
    state_data = await state.get_data()
    chosen_start = state_data.get("chosen_start")
    chosen_end = state_data.get("chosen_end")

    # Check if session expired (no chosen_start or chosen_end)
    if not chosen_start or not chosen_end:
        # Escape for MarkdownV2 safety
        await message.answer("Сессия истекла\\, вызовите /slots")
        logger.warning(
            "Session expired: no chosen_start/chosen_end",
            extra={"request_id": request_id},
        )
        return

    # Get title from message
    title = message.text.strip() if message.text else ""

    # Protect against empty title
    if not title:
        await message.answer("Пожалуйста, введите название события:")
        logger.warning(
            "Empty title received",
            extra={"request_id": request_id},
        )
        return

    # Create draft
    import uuid
    draft = {"title": title, "start_iso": chosen_start, "end_iso": chosen_end}
    draft_json = json.dumps(draft, ensure_ascii=False)
    draft_id = uuid.uuid4().hex[:8]

    # Save draft to state
    await state.update_data(draft_json=draft_json, draft_id=draft_id)

    # Parse ISO strings to datetime for display
    try:
        start_dt = datetime.fromisoformat(chosen_start)
        end_dt = datetime.fromisoformat(chosen_end)
        # Ensure aware UTC
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=UTC)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=UTC)
    except ValueError as e:
        logger.error(
            f"Invalid ISO format in state: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка данных. Вызовите /slots заново.")
        return

    # Format for display: ГГГГ-ММ-ДД ЧЧ:ММ UTC
    start_display = start_dt.strftime("%Y-%m-%d %H:%M UTC")
    end_display = end_dt.strftime("%Y-%m-%d %H:%M UTC")

    # Escape title for MarkdownV2
    from app.bot.keyboards import _escape_markdown_v2
    safe_title = _escape_markdown_v2(title)

    # Build confirmation message
    confirm_text = f'Создать событие "{safe_title}" {start_display}–{end_display}?'

    # Import keyboard
    from app.bot.keyboards import confirm_keyboard

    await message.answer(confirm_text, reply_markup=confirm_keyboard("create", draft_id))
    logger.info(
        f"Draft created: {draft_id}, title={title}",
        extra={"request_id": request_id},
    )


async def cb_confirm_create(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle event creation confirmation callback.

    Args:
        callback: Callback query from confirm button.
        state: FSM context for retrieving draft data.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info(f"Confirm callback received: {callback.data}", extra={"request_id": request_id})

    # Always answer callback
    await callback.answer()

    # Parse callback data
    callback_data = callback.data

    # Handle decline
    if callback_data == "cf:create:decline":
        await callback.message.answer("Отменено")
        await state.clear()
        logger.info("Event creation declined", extra={"request_id": request_id})
        return

    # Handle "Yes" - cf:create:<draft_id>
    if callback_data.startswith("cf:create:"):
        callback_draft_id = callback_data.replace("cf:create:", "")

        # Retrieve draft from state
        state_data = await state.get_data()
        draft_json = state_data.get("draft_json")
        stored_draft_id = state_data.get("draft_id")

        # Validate draft exists and IDs match
        if not draft_json or callback_draft_id != stored_draft_id:
            await callback.message.answer("Подтверждение устарело, вызовите /slots заново")
            logger.warning(
                f"Draft mismatch: callback={callback_draft_id}, stored={stored_draft_id}",
                extra={"request_id": request_id},
            )
            await state.clear()
            return

        # Parse draft
        try:
            draft = json.loads(draft_json)
            title = draft["title"]
            start_iso = draft["start_iso"]
            end_iso = draft["end_iso"]
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(
                f"Invalid draft JSON: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка данных. Вызовите /slots заново.")
            await state.clear()
            return

        # Parse ISO strings to aware UTC datetime
        try:
            start_dt = datetime.fromisoformat(start_iso)
            end_dt = datetime.fromisoformat(end_iso)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=UTC)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=UTC)
        except ValueError as e:
            logger.error(
                f"Invalid ISO format in draft: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка данных. Вызовите /slots заново.")
            await state.clear()
            return

        # Create event via CalendarService
        service = CalendarService()
        try:
            await service.authenticate()
        except CalendarAuthError as e:
            logger.error(
                f"Calendar auth failed: {e}",
                extra={"request_id": request_id},
            )
            # Polite error, do NOT notify admin, do NOT clear state
            await callback.message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
            return
        except CalendarAPIError as e:
            logger.error(
                f"Calendar API error during auth: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка календаря. Попробуйте позже.")
            return

        try:
            event_id = await service.create_event(title, start_dt, end_dt)
        except CalendarAuthError as e:
            logger.error(
                f"Calendar auth failed during create_event: {e}",
                extra={"request_id": request_id},
            )
            # Polite error, do NOT notify admin, do NOT clear state
            await callback.message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
            return
        except CalendarAPIError as e:
            logger.error(
                f"Calendar API error during create_event: {e}",
                extra={"request_id": request_id},
            )
            # Notify admin
            settings = get_settings()
            if settings.TELEGRAM_ADMIN_ID:
                try:
                    from aiogram import Bot
                    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
                    await bot.send_message(
                        chat_id=settings.TELEGRAM_ADMIN_ID,
                        text=f"Calendar API error in create_event: {e}",
                    )
                    await bot.session.close()
                except Exception:
                    pass
            # Polite error to user, do NOT clear state
            await callback.message.answer("Ошибка календаря. Попробуйте позже.")
            return
        except Exception as e:
            logger.error(
                f"Unexpected error during create_event: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Неожиданная ошибка. Попробуйте позже.")
            return

        # Success
        # Escape event_id for MarkdownV2
        safe_event_id = _escape_markdown_v2(str(event_id))
        await callback.message.answer(f"Создано, event_id={safe_event_id}")
        await state.clear()
        logger.info(
            f"Event created: {event_id}, title={title}",
            extra={"request_id": request_id},
        )
        return

    # Unknown callback data format
    logger.warning(
        f"Unknown callback data format: {callback_data}",
        extra={"request_id": request_id},
    )


async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Handle /cancel command - cancel an event by ID.

    Args:
        message: Incoming message with /cancel <event_id>.
        state: FSM context (not used here).
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info("/cancel command received", extra={"request_id": request_id})

    # Parse event_id from command text
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "Использование: /cancel <event_id>\n"
            "Пример: /cancel abc123xyz"
        )
        logger.warning(
            "/cancel called without event_id",
            extra={"request_id": request_id},
        )
        return

    event_id = parts[1]

    # Authenticate and get event
    service = CalendarService()
    try:
        await service.authenticate()
    except CalendarAuthError as e:
        logger.error(
            f"Calendar auth failed: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
        return
    except CalendarAPIError as e:
        logger.error(
            f"Calendar API error during auth: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка календаря. Попробуйте позже.")
        return

    try:
        event = await service.get_event(event_id)
    except CalendarAuthError as e:
        logger.error(
            f"Calendar auth failed in get_event: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
        return
    except CalendarAPIError as e:
        logger.error(
            f"Event not found or API error: {e}",
            extra={"request_id": request_id},
        )
        if "Event not found" in str(e):
            await message.answer("Событие не найдено")
        else:
            # Notify admin for API errors
            settings = get_settings()
            if settings.TELEGRAM_ADMIN_ID:
                try:
                    from aiogram import Bot
                    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
                    await bot.send_message(
                        chat_id=settings.TELEGRAM_ADMIN_ID,
                        text=f"Calendar API error in /cancel: {e}",
                    )
                    await bot.session.close()
                except Exception:
                    pass
            await message.answer("Ошибка календаря. Попробуйте позже.")
        return

    # Event found - show summary and ask for confirmation
    title = event.get("summary", "Без названия")
    start_iso = event.get("start")
    end_iso = event.get("end")

    # Parse and format times in UTC
    try:
        start_dt = datetime.fromisoformat(start_iso) if start_iso else None
        end_dt = datetime.fromisoformat(end_iso) if end_iso else None
        if start_dt and start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=UTC)
        if end_dt and end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=UTC)
        start_display = start_dt.strftime("%Y-%m-%d %H:%M UTC") if start_dt else "?"
        end_display = end_dt.strftime("%Y-%m-%d %H:%M UTC") if end_dt else "?"
    except (ValueError, TypeError) as e:
        logger.error(
            f"Invalid date format in event: {e}",
            extra={"request_id": request_id},
        )
        start_display = "?"
        end_display = "?"

    safe_title = _escape_markdown_v2(title)
    safe_start = _escape_markdown_v2(start_display)
    safe_end = _escape_markdown_v2(end_display)

    summary_text = (
        f"Событие: {safe_title}\\n"
        f"Начало: {safe_start}\\n"
        f"Конец: {safe_end}"
    )

    from app.bot.keyboards import confirm_keyboard
    await message.answer(summary_text, reply_markup=confirm_keyboard("delete", event_id))
    logger.info(
        f"Showed delete confirmation for event {event_id}",
        extra={"request_id": request_id},
    )


async def cmd_update(message: Message, state: FSMContext) -> None:
    """Handle /update command - update an event by ID.

    Args:
        message: Incoming message with /update <event_id>.
        state: FSM context for storing snapshot.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info("/update command received", extra={"request_id": request_id})

    # Parse event_id from command text
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "Использование: /update <event_id>\n"
            "Пример: /update abc123xyz"
        )
        logger.warning(
            "/update called without event_id",
            extra={"request_id": request_id},
        )
        return

    event_id = parts[1]

    # Authenticate and get event
    service = CalendarService()
    try:
        await service.authenticate()
    except CalendarAuthError as e:
        logger.error(
            f"Calendar auth failed: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
        return
    except CalendarAPIError as e:
        logger.error(
            f"Calendar API error during auth: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка календаря. Попробуйте позже.")
        return

    try:
        event = await service.get_event(event_id)
    except CalendarAuthError as e:
        logger.error(
            f"Calendar auth failed in get_event: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
        return
    except CalendarAPIError as e:
        logger.error(
            f"Event not found or API error: {e}",
            extra={"request_id": request_id},
        )
        if "Event not found" in str(e):
            await message.answer("Событие не найдено")
        else:
            settings = get_settings()
            if settings.TELEGRAM_ADMIN_ID:
                try:
                    from aiogram import Bot
                    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
                    await bot.send_message(
                        chat_id=settings.TELEGRAM_ADMIN_ID,
                        text=f"Calendar API error in /update: {e}",
                    )
                    await bot.session.close()
                except Exception:
                    pass
            await message.answer("Ошибка календаря. Попробуйте позже.")
        return

    # Event found - save snapshot and set state
    old_title = event.get("summary", "")
    old_start_iso = event.get("start", "")
    old_end_iso = event.get("end", "")

    snapshot = {
        "event_id": event_id,
        "old_title": old_title,
        "old_start_iso": old_start_iso,
        "old_end_iso": old_end_iso,
    }
    await state.update_data(snapshot=snapshot)
    await state.set_state(SecretaryStates.waiting_update)

    instruction = (
        "Пришли новые данные в формате:\n"
        "заголовок | ГГГГ-ММ-ДД ЧЧ:ММ | ГГГГ-ММ-ДД ЧЧ:ММ\n"
        "(пустые части сохраняют старые значения)"
    )
    await message.answer(instruction)
    logger.info(
        f"Set waiting_update state for event {event_id}",
        extra={"request_id": request_id},
    )


async def msg_waiting_update(message: Message, state: FSMContext) -> None:
    """Handle user input in waiting_update state.

    Args:
        message: Incoming message with update data.
        state: FSM context containing snapshot.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info("Waiting for update input", extra={"request_id": request_id})

    # Get snapshot from state
    state_data = await state.get_data()
    snapshot = state_data.get("snapshot")

    if not snapshot:
        await message.answer("Сессия истекла, вызовите /update заново")
        logger.warning(
            "No snapshot in state",
            extra={"request_id": request_id},
        )
        await state.clear()
        return

    event_id = snapshot.get("event_id")
    old_title = snapshot.get("old_title", "")
    old_start_iso = snapshot.get("old_start_iso", "")
    old_end_iso = snapshot.get("old_end_iso", "")

    # Parse input: title | start | end
    text = message.text.strip() if message.text else ""
    parts = text.split("|", maxsplit=2)

    if len(parts) > 3:
        await message.answer(
            "Неверный формат. Используйте:\n"
            "заголовок | ГГГГ-ММ-ДД ЧЧ:ММ | ГГГГ-ММ-ДД ЧЧ:ММ\n"
            "(пустые части сохраняют старые значения)"
        )
        logger.warning(
            "Invalid format: more than 3 parts",
            extra={"request_id": request_id},
        )
        return

    # Pad parts to 3
    while len(parts) < 3:
        parts.append("")

    new_title_raw = parts[0].strip() or None
    new_start_raw = parts[1].strip() or None
    new_end_raw = parts[2].strip() or None

    # Merge with old values
    title = new_title_raw if new_title_raw else old_title
    start_raw = new_start_raw if new_start_raw else old_start_iso
    end_raw = new_end_raw if new_end_raw else old_end_iso

    # Parse dates in user timezone -> UTC
    settings = get_settings()
    user_tz = ZoneInfo(str(settings.TIMEZONE))

    try:
        if new_start_raw:
            start_dt = datetime.strptime(start_raw, "%Y-%m-%d %H:%M")
            start_dt = start_dt.replace(tzinfo=user_tz)
            start_utc = start_dt.astimezone(UTC)
        else:
            start_dt = datetime.fromisoformat(old_start_iso) if old_start_iso else None
            if start_dt and start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=UTC)
            start_utc = start_dt

        if new_end_raw:
            end_dt = datetime.strptime(end_raw, "%Y-%m-%d %H:%M")
            end_dt = end_dt.replace(tzinfo=user_tz)
            end_utc = end_dt.astimezone(UTC)
        else:
            end_dt = datetime.fromisoformat(old_end_iso) if old_end_iso else None
            if end_dt and end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=UTC)
            end_utc = end_dt
    except (ValueError, TypeError) as e:
        logger.error(
            f"Invalid date format: {e}",
            extra={"request_id": request_id},
        )
        await message.answer(
            "Неверный формат даты. Используйте ГГГГ-ММ-ДД ЧЧ:ММ\n"
            "Повторите ввод в формате:\n"
            "заголовок | ГГГГ-ММ-ДД ЧЧ:ММ | ГГГГ-ММ-ДД ЧЧ:ММ"
        )
        return

    # Create draft
    import uuid
    draft = {
        "event_id": event_id,
        "title": title,
        "start_iso": start_utc.isoformat() if start_utc else "",
        "end_iso": end_utc.isoformat() if end_utc else "",
    }
    draft_id = uuid.uuid4().hex[:8]
    await state.update_data(draft=draft, draft_id=draft_id)

    # Format display times
    start_display = start_utc.strftime("%Y-%m-%d %H:%M UTC") if start_utc else "?"
    end_display = end_utc.strftime("%Y-%m-%d %H:%M UTC") if end_utc else "?"

    safe_title = _escape_markdown_v2(title)
    safe_start = _escape_markdown_v2(start_display)
    safe_end = _escape_markdown_v2(end_display)

    question = f'Изменить событие "{safe_title}" на {safe_start}–{safe_end}?'

    from app.bot.keyboards import confirm_keyboard
    await message.answer(question, reply_markup=confirm_keyboard("update", draft_id))
    logger.info(
        f"Created update draft {draft_id} for event {event_id}",
        extra={"request_id": request_id},
    )


async def cb_confirm_update(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle update confirmation callback.

    Args:
        callback: Callback query from confirm button.
        state: FSM context containing draft.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info(f"Update confirm callback: {callback.data}", extra={"request_id": request_id})

    # Always answer callback
    await callback.answer()

    callback_data = callback.data

    # Handle decline
    if callback_data == "cf:update:decline":
        await callback.message.answer("Отменено")
        await state.clear()
        logger.info("Update declined", extra={"request_id": request_id})
        return

    # Handle "Yes" - cf:update:<draft_id>
    if callback_data.startswith("cf:update:"):
        callback_draft_id = callback_data.replace("cf:update:", "")

        # Retrieve draft from state
        state_data = await state.get_data()
        draft = state_data.get("draft")
        stored_draft_id = state_data.get("draft_id")

        # Validate draft exists and IDs match
        if not draft or callback_draft_id != stored_draft_id:
            await callback.message.answer("Подтверждение устарело, вызовите /update заново")
            logger.warning(
                f"Draft mismatch: callback={callback_draft_id}, stored={stored_draft_id}",
                extra={"request_id": request_id},
            )
            await state.clear()
            return

        # Extract data from draft
        event_id = draft.get("event_id")
        title = draft.get("title", "")
        start_iso = draft.get("start_iso", "")
        end_iso = draft.get("end_iso", "")

        # Parse datetimes
        try:
            start_dt = datetime.fromisoformat(start_iso) if start_iso else None
            end_dt = datetime.fromisoformat(end_iso) if end_iso else None
            if start_dt and start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=UTC)
            if end_dt and end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=UTC)
        except (ValueError, TypeError) as e:
            logger.error(
                f"Invalid ISO format in draft: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка данных. Вызовите /update заново.")
            await state.clear()
            return

        # Authenticate and update event
        service = CalendarService()
        try:
            await service.authenticate()
        except CalendarAuthError as e:
            logger.error(
                f"Calendar auth failed: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
            return
        except CalendarAPIError as e:
            logger.error(
                f"Calendar API error during auth: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка календаря. Попробуйте позже.")
            return

        try:
            await service.update_event(
                event_id=event_id,
                summary=title,
                start_time=start_dt,
                end_time=end_dt,
            )
        except CalendarAuthError as e:
            logger.error(
                f"Calendar auth failed in update_event: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
            return
        except CalendarAPIError as e:
            logger.error(
                f"Calendar API error in update_event: {e}",
                extra={"request_id": request_id},
            )
            # Notify admin
            settings = get_settings()
            if settings.TELEGRAM_ADMIN_ID:
                try:
                    from aiogram import Bot
                    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
                    await bot.send_message(
                        chat_id=settings.TELEGRAM_ADMIN_ID,
                        text=f"Calendar API error in update_event: {e}",
                    )
                    await bot.session.close()
                except Exception:
                    pass
            await callback.message.answer("Ошибка календаря. Попробуйте позже.")
            return

        # Success
        safe_event_id = _escape_markdown_v2(str(event_id))
        await callback.message.answer(f"Обновлено, event_id={safe_event_id}")
        await state.clear()
        logger.info(
            f"Event updated: {event_id}, title={title}",
            extra={"request_id": request_id},
        )
        return

    # Unknown callback data format
    logger.warning(
        f"Unknown callback data format: {callback_data}",
        extra={"request_id": request_id},
    )


async def cb_confirm_delete(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle delete confirmation callback.

    Args:
        callback: Callback query from confirm button.
        state: FSM context (not used here).
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info(f"Delete confirm callback: {callback.data}", extra={"request_id": request_id})

    # Always answer callback
    await callback.answer()

    callback_data = callback.data

    # Handle decline
    if callback_data == "cf:delete:decline":
        await callback.message.answer("Отменено")
        logger.info("Delete declined", extra={"request_id": request_id})
        return

    # Handle "Yes" - cf:delete:<event_id>
    if callback_data.startswith("cf:delete:"):
        event_id = callback_data.replace("cf:delete:", "")

        # Authenticate and delete event
        service = CalendarService()
        try:
            await service.authenticate()
        except CalendarAuthError as e:
            logger.error(
                f"Calendar auth failed: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
            return
        except CalendarAPIError as e:
            logger.error(
                f"Calendar API error during auth: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка календаря. Попробуйте позже.")
            return

        try:
            await service.delete_event(event_id)
        except CalendarAuthError as e:
            logger.error(
                f"Calendar auth failed in delete_event: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
            return
        except CalendarAPIError as e:
            logger.error(
                f"Calendar API error in delete_event: {e}",
                extra={"request_id": request_id},
            )
            if "Event not found" in str(e):
                await callback.message.answer("Событие не найдено")
            else:
                # Notify admin
                settings = get_settings()
                if settings.TELEGRAM_ADMIN_ID:
                    try:
                        from aiogram import Bot
                        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
                        await bot.send_message(
                            chat_id=settings.TELEGRAM_ADMIN_ID,
                            text=f"Calendar API error in delete_event: {e}",
                        )
                        await bot.session.close()
                    except Exception:
                        pass
                await callback.message.answer("Ошибка календаря. Попробуйте позже.")
            return

        # Success
        safe_event_id = _escape_markdown_v2(str(event_id))
        await callback.message.answer(f"Удалено, event_id={safe_event_id}")
        logger.info(
            f"Event deleted: {event_id}",
            extra={"request_id": request_id},
        )
        return

    # Unknown callback data format
    logger.warning(
        f"Unknown callback data format: {callback_data}",
        extra={"request_id": request_id},
    )

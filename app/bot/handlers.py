"""Telegram bot handlers for MedNews Secretary Agent (Task 8b/8c/8d).

Provides /slots command, slot selection callback handler, and event management handlers.
"""

import asyncio
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
    waiting_update_time = State()


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


async def cmd_update(message: Message, state: FSMContext) -> None:
    """Handle /update command - show user's upcoming events for update.

    Args:
        message: Incoming message with /update command.
        state: FSM context for storing event data.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info("/update command received", extra={"request_id": request_id})

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

    # Get upcoming events (next 7 days)
    from datetime import timedelta
    now = datetime.now(UTC)
    time_min = now
    time_max = now + timedelta(days=7)

    try:
        calendar_service = await service._get_service()
        
        events_result = await asyncio.to_thread(
            calendar_service.events().list(
                calendarId="primary",
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            ).execute
        )
        events = events_result.get("items", [])
    except CalendarAuthError as e:
        logger.error(
            f"Calendar auth failed while listing events: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
        return
    except CalendarAPIError as e:
        logger.error(
            f"Calendar API error while listing events: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка календаря. Попробуйте позже.")
        return

    if not events:
        await message.answer("Нет предстоящих событий в ближайшие 7 дней")
        logger.info("No upcoming events found for update", extra={"request_id": request_id})
        return

    # Limit to 3 events max
    limited_events = events[:3]

    # Store events in state
    events_data = []
    for idx, event in enumerate(limited_events):
        event_id = event.get("id", "")
        summary = event.get("summary", "Без названия")
        start_iso = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end_iso = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
        events_data.append({
            "id": event_id,
            "summary": summary,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "idx": idx,
        })

    await state.update_data(update_events=events_data)

    # Build message with events
    msg_lines = ["Выберите событие для обновления (отправьте номер 1-3):"]
    for ev in events_data:
        try:
            start_dt = datetime.fromisoformat(ev["start_iso"])
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=UTC)
            start_display = start_dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, KeyError):
            start_display = ev["start_iso"]
        
        msg_lines.append(f"{ev['idx'] + 1}. {ev['summary']} — {start_display}")

    await message.answer("\n".join(msg_lines))
    await state.update_state(SecretaryStates.waiting_update_time)
    logger.info(
        f"Sent {len(limited_events)} events for update selection",
        extra={"request_id": request_id},
    )


async def msg_waiting_update(message: Message, state: FSMContext) -> None:
    """Handle user input of new date/time for event update.

    Args:
        message: Incoming message with new date/time.
        state: FSM context for retrieving event data.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info(f"Received update time input: {message.text}", extra={"request_id": request_id})

    # Get state data
    state_data = await state.get_data()
    update_events = state_data.get("update_events", [])
    selected_idx = state_data.get("update_selected_idx")

    if not update_events or selected_idx is None:
        await message.answer("Сессия истекла, вызовите /update заново")
        await state.clear()
        logger.warning("Update session expired", extra={"request_id": request_id})
        return

    # Get selected event
    event = update_events[selected_idx]
    event_id = event.get("id")
    event_summary = event.get("summary")

    # Parse user input as new datetime
    user_text = message.text.strip()
    
    # Try to parse ISO format or common formats
    new_start_dt = None
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y"]:
        try:
            new_start_dt = datetime.strptime(user_text, fmt)
            new_start_dt = new_start_dt.replace(tzinfo=UTC)
            break
        except ValueError:
            continue
    
    if new_start_dt is None:
        await message.answer("Неверный формат даты. Используйте YYYY-MM-DD HH:MM")
        logger.warning(f"Invalid date format: {user_text}", extra={"request_id": request_id})
        return

    # Calculate new end time (same duration as original)
    try:
        orig_start = datetime.fromisoformat(event["start_iso"])
        if orig_start.tzinfo is None:
            orig_start = orig_start.replace(tzinfo=UTC)
        orig_end = datetime.fromisoformat(event["end_iso"])
        if orig_end.tzinfo is None:
            orig_end = orig_end.replace(tzinfo=UTC)
        duration = orig_end - orig_start
        new_end_dt = new_start_dt + duration
    except (KeyError, ValueError) as e:
        await message.answer("Ошибка вычисления времени события")
        logger.error(f"Error calculating new event time: {e}", extra={"request_id": request_id})
        return

    # Store new times in state
    await state.update_data(
        new_start_iso=new_start_dt.isoformat(),
        new_end_iso=new_end_dt.isoformat(),
    )

    # Show confirmation with new times
    from app.bot.keyboards import confirm_keyboard
    
    start_display = new_start_dt.strftime("%Y-%m-%d %H:%M UTC")
    end_display = new_end_dt.strftime("%Y-%m-%d %H:%M UTC")
    
    await message.answer(
        f"Обновить событие \"{event_summary}\"?\n"
        f"Новое время: {start_display} – {end_display}",
        reply_markup=confirm_keyboard("update", event_id),
    )
    logger.info(f"Update confirmation sent for event {event_id}", extra={"request_id": request_id})


async def cb_confirm_update(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle event update confirmation callback.

    Args:
        callback: Callback query from confirm button.
        state: FSM context for retrieving event data.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info(
        f"Update confirm callback received: {callback.data}",
        extra={"request_id": request_id},
    )

    # Always answer callback
    await callback.answer()

    # Handle decline
    if callback.data == "cf:update:decline":
        await callback.message.answer("Отменено")
        await state.clear()
        logger.info("Event update declined", extra={"request_id": request_id})
        return

    # Handle "Yes" - cf:update:<event_id>
    if callback.data.startswith("cf:update:"):
        event_id = callback.data.replace("cf:update:", "")

        # Retrieve event from state to validate
        state_data = await state.get_data()
        stored_event_id = state_data.get("update_event_id")
        new_start_iso = state_data.get("new_start_iso")
        new_end_iso = state_data.get("new_end_iso")

        if not event_id or event_id != stored_event_id:
            await callback.message.answer("Подтверждение устарело, вызовите /update заново")
            logger.warning(
                f"Event ID mismatch: callback={event_id}, stored={stored_event_id}",
                extra={"request_id": request_id},
            )
            await state.clear()
            return

        if not new_start_iso or not new_end_iso:
            await callback.message.answer("Ошибка: данные времени не найдены")
            logger.warning("Missing new time data in state", extra={"request_id": request_id})
            await state.clear()
            return

        # Update event via CalendarService
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
            await service.update_event(event_id, new_start_iso, new_end_iso)
        except CalendarAuthError as e:
            logger.error(
                f"Calendar auth failed during update_event: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
            return
        except CalendarAPIError as e:
            logger.error(
                f"Calendar API error during update_event: {e}",
                extra={"request_id": request_id},
            )
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
        await callback.message.answer("Событие обновлено")
        await state.clear()
        logger.info(f"Event updated: {event_id}", extra={"request_id": request_id})
        return

    # Unknown callback data format
    logger.warning(
        f"Unknown callback data format: {callback.data}",
        extra={"request_id": request_id},
    )


async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Handle /cancel command - show user's upcoming events for cancellation.

    Args:
        message: Incoming message with /cancel command.
        state: FSM context for storing event data.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info("/cancel command received", extra={"request_id": request_id})

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

    # Get upcoming events (next 7 days)
    from datetime import timedelta
    now = datetime.now(UTC)
    time_min = now
    time_max = now + timedelta(days=7)

    try:
        # Use find_available_slots to get events (it lists existing events too)
        # We need to list user's events - use internal _list_events logic
        # find_available_slots returns FREE slots, we need BUSY slots (events)
        # Let's call the internal method directly
        calendar_service = await service._get_service()
        
        events_result = await asyncio.to_thread(
            calendar_service.events().list(
                calendarId="primary",
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            ).execute
        )
        events = events_result.get("items", [])
    except CalendarAuthError as e:
        logger.error(
            f"Calendar auth failed while listing events: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
        return
    except CalendarAPIError as e:
        logger.error(
            f"Calendar API error while listing events: {e}",
            extra={"request_id": request_id},
        )
        await message.answer("Ошибка календаря. Попробуйте позже.")
        return

    if not events:
        await message.answer("Нет предстоящих событий в ближайшие 7 дней")
        logger.info("No upcoming events found", extra={"request_id": request_id})
        return

    # Limit to 3 events max
    limited_events = events[:3]

    # Store events in state
    events_data = []
    for idx, event in enumerate(limited_events):
        event_id = event.get("id", "")
        summary = event.get("summary", "Без названия")
        start_iso = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end_iso = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
        events_data.append({
            "id": event_id,
            "summary": summary,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "idx": idx,
        })

    await state.update_data(cancel_events=events_data)

    # Build message with events
    from app.bot.keyboards import _escape_markdown_v2
    
    msg_lines = ["Выберите событие для отмены:"]
    for ev in events_data:
        try:
            start_dt = datetime.fromisoformat(ev["start_iso"])
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=UTC)
            start_display = start_dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, KeyError):
            start_display = ev["start_iso"]
        
        safe_summary = _escape_markdown_v2(ev["summary"])
        msg_lines.append(f"{ev['idx'] + 1}\\. {safe_summary} — {start_display}")

    await message.answer("\n".join(msg_lines))
    logger.info(
        f"Sent {len(limited_events)} events for cancellation",
        extra={"request_id": request_id},
    )


async def cb_confirm_delete(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle event deletion confirmation callback.

    Args:
        callback: Callback query from confirm button.
        state: FSM context for retrieving event data.
    """
    request_id = new_request_id()
    logger = get_logger("bot")
    logger.info(
        f"Delete confirm callback received: {callback.data}",
        extra={"request_id": request_id},
    )

    # Always answer callback
    await callback.answer()

    # Handle decline
    if callback.data == "cf:delete:decline":
        await callback.message.answer("Отменено")
        await state.clear()
        logger.info("Event deletion declined", extra={"request_id": request_id})
        return

    # Handle "Yes" - cf:delete:<event_id>
    if callback.data.startswith("cf:delete:"):
        event_id = callback.data.replace("cf:delete:", "")

        # Retrieve event from state to validate
        state_data = await state.get_data()
        stored_event_id = state_data.get("delete_event_id")

        if not event_id or event_id != stored_event_id:
            await callback.message.answer("Подтверждение устарело, вызовите /cancel заново")
            logger.warning(
                f"Event ID mismatch: callback={event_id}, stored={stored_event_id}",
                extra={"request_id": request_id},
            )
            await state.clear()
            return

        # Delete event via CalendarService
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
                f"Calendar auth failed during delete_event: {e}",
                extra={"request_id": request_id},
            )
            await callback.message.answer("Ошибка аутентификации календаря. Попробуйте позже.")
            return
        except CalendarAPIError as e:
            logger.error(
                f"Calendar API error during delete_event: {e}",
                extra={"request_id": request_id},
            )
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
        await callback.message.answer("Событие отменено")
        await state.clear()
        logger.info(f"Event deleted: {event_id}", extra={"request_id": request_id})
        return

    # Unknown callback data format
    logger.warning(
        f"Unknown callback data format: {callback.data}",
        extra={"request_id": request_id},
    )

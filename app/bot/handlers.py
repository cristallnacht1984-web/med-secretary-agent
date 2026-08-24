"""Telegram bot handlers for MedNews Secretary Agent (Task 8b).

Provides /slots command and slot selection callback handler.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import get_settings
from app.logging_setup import get_logger, new_request_id
from app.services.calendar_service import CalendarAPIError, CalendarAuthError, CalendarService


class SecretaryStates(StatesGroup):
    """FSM states for secretary flow."""

    waiting_title = State()


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

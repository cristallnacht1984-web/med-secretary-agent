"""Telegram bot keyboards for MedNews Secretary Agent.

Provides inline keyboard builders for calendar slots and confirmation dialogs.
"""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _escape_markdown_v2(text: str) -> str:
    """Escape MarkdownV2 special characters in button text.

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


def slots_keyboard(slots: list[dict]) -> InlineKeyboardMarkup:
    """Inline-клавиатура свободных слотов (максимум 3).

    По одной кнопке на слот. callback_data: 'slot:<idx>' (idx = 0..2).
    Подпись кнопки — из ключей start_display/end_display dict-слота.
    Жёстко обрезает вход до 3 слотов, даже если пришло больше.
    При 0 слотов возвращает заглушку с некликабельной кнопкой.

    Args:
        slots: List of slot dicts from CalendarService.find_available_slots().
               Each dict has keys: start, end, start_display, end_display.

    Returns:
        InlineKeyboardMarkup with up to 3 buttons, or stub markup for 0 slots.
    """
    builder = InlineKeyboardBuilder()

    # Hard limit to 3 slots per AGENTS.md CALENDAR RULES
    limited_slots = slots[:3]

    if not limited_slots:
        # Stub for no available slots
        builder.button(
            text="Нет доступных слотов",
            callback_data="slot:none",
        )
        return builder.as_markup()

    for idx, slot in enumerate(limited_slots):
        # Extract display strings from slot dict
        start_display = slot.get("start_display", "Unknown")
        end_display = slot.get("end_display", "Unknown")

        # Escape for MarkdownV2 safety
        safe_start = _escape_markdown_v2(start_display)
        safe_end = _escape_markdown_v2(end_display)

        button_text = f"{safe_start} – {safe_end}"
        callback_data = f"slot:{idx}"

        builder.button(
            text=button_text,
            callback_data=callback_data,
        )

    return builder.as_markup()


def confirm_keyboard(action: str, payload: str) -> InlineKeyboardMarkup:
    """Две кнопки Да/Нет для подтверждения write-операции.

    'Да'  -> callback_data: 'cf:<action>:<payload>'
    'Нет' -> callback_data: 'cf:<action>:decline'

    callback_data суммарно ≤ 64 байт. Если payload превышает лимит,
    он усекается детерминированно (берётся начало строки).

    Args:
        action: Action identifier (e.g., 'create', 'update', 'delete').
        payload: Payload string to be encoded in callback_data.
                 Will be truncated to fit 64-byte limit.

    Returns:
        InlineKeyboardMarkup with Yes/No buttons.
    """
    builder = InlineKeyboardBuilder()

    # Build callback_data strings
    # Format: cf:<action>:<payload>
    # Max length is 64 bytes
    prefix = f"cf:{action}:"
    max_payload_bytes = 64 - len(prefix.encode()) - len(b":decline")

    # Truncate payload if needed to fit 64-byte limit
    payload_bytes = payload.encode("utf-8")
    if len(payload_bytes) > max_payload_bytes:
        # Truncate deterministically: take the beginning
        payload_bytes = payload_bytes[:max_payload_bytes]
        payload = payload_bytes.decode("utf-8", errors="ignore")

    yes_callback = f"{prefix}{payload}"
    no_callback = f"cf:{action}:decline"

    builder.button(
        text="Да",
        callback_data=yes_callback,
    )
    builder.button(
        text="Нет",
        callback_data=no_callback,
    )

    # Arrange buttons in a row
    builder.adjust(2)

    return builder.as_markup()

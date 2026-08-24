"""Telegram bot filters for MedNews Secretary Agent.

Provides whitelist filter to restrict bot access to authorized users only.
"""

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import get_settings
from app.logging_setup import get_logger, new_request_id

logger = get_logger("bot")


class WhitelistFilter(BaseFilter):
    """Пропускает ТОЛЬКО user_id из settings.TELEGRAM_ALLOWED_USER_IDS.

    Чужие user_id отклоняются полностью (return False), без обработки.
    Работает и для Message, и для CallbackQuery.
    Список берётся из get_settings().TELEGRAM_ALLOWED_USER_IDS каждый раз
    при вызове (НЕ кешируется на уровне класса).
    """

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        """Check if event's user_id is in the whitelist.

        Args:
            event: aiogram Message or CallbackQuery event.

        Returns:
            True if user_id is in TELEGRAM_ALLOWED_USER_IDS, False otherwise.
        """
        request_id = new_request_id()
        user_id = event.from_user.id
        allowed_ids = get_settings().TELEGRAM_ALLOWED_USER_IDS

        if user_id in allowed_ids:
            return True

        logger.warning(
            f"Unauthorized user attempt: user_id={user_id}",
            extra={"request_id": request_id},
        )
        return False

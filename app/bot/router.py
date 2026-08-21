"""Telegram bot router for MedNews Secretary Agent.

Provides the base router with whitelist filter registered for messages and callbacks.
Business handlers will be added in subsequent tasks (8b/8c).
"""

from aiogram import Router

from app.bot.filters import WhitelistFilter


def build_router() -> Router:
    """Возвращает aiogram Router с WhitelistFilter.

    Фильтр зарегистрирован ОДНОВРЕМЕННО на message и callback_query.
    Бизнес-хэндлеры 8b/8c будут добавлены позже — в 8a их НЕТ.

    Returns:
        Router with WhitelistFilter applied to message and callback_query.
    """
    router = Router()

    # Register whitelist filter on both message and callback_query
    whitelist_filter = WhitelistFilter()
    router.message.filter(whitelist_filter)
    router.callback_query.filter(whitelist_filter)

    return router

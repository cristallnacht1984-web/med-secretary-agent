"""Telegram bot router for MedNews Secretary Agent.

Provides the base router with whitelist filter registered for messages and callbacks.
Business handlers are added for Task 8b (/slots command and slot selection).
"""

from aiogram import F, Router
from aiogram.filters import Command

from app.bot.filters import WhitelistFilter
from app.bot.handlers import cb_slot, cmd_slots


def build_router() -> Router:
    """Возвращает aiogram Router с WhitelistFilter и хэндлерами 8b.

    Фильтр зарегистрирован ОДНОВРЕМЕННО на message и callback_query.
    Хэндлеры 8b: cmd_slots (Command("slots")), cb_slot (F.data.startswith("slot:")).

    Returns:
        Router with WhitelistFilter and 8b handlers registered.
    """
    router = Router()

    # Register whitelist filter on both message and callback_query
    whitelist_filter = WhitelistFilter()
    router.message.filter(whitelist_filter)
    router.callback_query.filter(whitelist_filter)

    # Register 8b handlers
    router.message.register(cmd_slots, Command("slots"))
    router.callback_query.register(cb_slot, F.data.startswith("slot:"))

    return router

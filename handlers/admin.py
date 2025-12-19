"""Administrative commands."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from services.settings_service import SettingsService

router = Router()


@router.message(Command("setgroup"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def set_orders_group(message: Message, settings_service: SettingsService) -> None:
    """Persist the group chat ID for order notifications."""

    chat_id = message.chat.id
    await settings_service.set("orders_group_id", str(chat_id))
    await message.answer("✅ Групу для замовлень успішно збережено")

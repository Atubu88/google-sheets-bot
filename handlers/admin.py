"""Administrative commands."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from services.product_service import ProductService
from services.promo_scheduler import broadcast_promo
from services.settings_service import SettingsService
from services.user_service import UserService

router = Router()


@router.message(Command("setgroup"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def set_orders_group(message: Message, settings_service: SettingsService) -> None:
    """Persist the group chat ID for order notifications."""

    chat_id = message.chat.id
    await settings_service.set("orders_group_id", str(chat_id))
    await message.answer("✅ Групу для замовлень успішно збережено")


@router.message(Command("sendpromo"))
async def send_promo(
    message: Message,
    product_service: ProductService,
    user_service: UserService,
) -> None:
    """Manually trigger promo broadcast without touching scheduler settings."""

    result = await broadcast_promo(message.bot, product_service, user_service)

    if result.status == "sent":
        await message.answer(
            f"✅ Промо-розсилку виконано (чатів: {result.chats}, товарів: {result.products})"
        )
        return

    if result.status == "no_products":
        await message.answer("⚠️ Немає товарів для промо-розсилки")
        return

    if result.status == "no_chats":
        await message.answer("⚠️ Немає користувачів для промо-розсилки")
        return

    await message.answer("❌ Помилка під час промо-розсилки")


@router.message(Command("stats"))
async def show_stats(message: Message, user_service: UserService) -> None:
    """Display user statistics."""

    stats = await user_service.get_statistics()
    await message.answer(
        "📊 Статистика користувачів\n"
        f"Всього: {stats['total']}\n"
        f"Активні: {stats['active']}\n"
        f"Відписались: {stats['left']}"
    )

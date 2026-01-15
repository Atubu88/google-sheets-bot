"""Administrative commands."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from services.product_service import ProductService
from services.promo_scheduler import broadcast_promo
from services.safe_sender import SafeSender
from services.settings_service import SettingsService
from services.user_service import UserService

router = Router()


@router.message(Command("setgroup"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def set_orders_group(
    message: Message,
    settings_service: SettingsService,
    safe_sender: SafeSender,
) -> None:
    """Persist the group chat ID for order notifications."""

    chat_id = message.chat.id
    await settings_service.set("orders_group_id", str(chat_id))
    await safe_sender.answer(message, "✅ Групу для замовлень успішно збережено")


@router.message(Command("sendpromo"))
async def send_promo(
    message: Message,
    product_service: ProductService,
    user_service: UserService,
    safe_sender: SafeSender,
) -> None:
    """Manually trigger promo broadcast without touching scheduler settings."""

    result = await broadcast_promo(safe_sender, product_service, user_service)

    if result.status == "sent":
        await safe_sender.answer(
            message,
            f"✅ Промо-розсилку виконано (чатів: {result.chats}, товарів: {result.products})"
        )
        return

    if result.status == "no_products":
        await safe_sender.answer(message, "⚠️ Немає товарів для промо-розсилки")
        return

    if result.status == "no_chats":
        await safe_sender.answer(message, "⚠️ Немає користувачів для промо-розсилки")
        return

    await safe_sender.answer(message, "❌ Помилка під час промо-розсилки")


@router.message(Command("stats"))
async def stats_handler(
    message: Message,
    user_service: UserService,
    safe_sender: SafeSender,
) -> None:
    stats = await user_service.get_statistics()
    await safe_sender.answer(
        message,
        (
            "📊 Статистика бота\n"
            f"👥 Всего: {stats.total}\n"
            f"✅ Активні: {stats.active}\n"
            f"🚫 Відписались: {stats.left}"
        ),
    )

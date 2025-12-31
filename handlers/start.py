"""Handlers related to the /start command."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.buy import (
    build_product_caption,
    remember_product_card,
    reset_product_cards,
    remember_welcome_message,
)
from services.product_service import ProductService, Product
from services.user_service import UserService


router = Router()


async def _send_product_card(message: Message, product: Product) -> Message:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Купити", callback_data=f"buy:{product.id}")

    return await message.answer_photo(
        photo=product.photo_url,
        caption=build_product_caption(product),
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML",
    )


@router.message(CommandStart())
async def start_handler(
    message: Message,
    product_service: ProductService,
    user_service: UserService,
) -> None:
    user = message.from_user

    # --- Сохраняем пользователя В ФОНЕ (и не ломаем webhook) ---
    if user:
        async def safe_save():
            try:
                await user_service.ensure_user_record(
                    user_id=user.id,
                    chat_id=message.chat.id,
                    username=user.username,
                    first_name=user.first_name,
                    created_at=datetime.now(timezone.utc),
                )
            except Exception:
                pass  # важно: не роняем webhook

        asyncio.create_task(safe_save())

    name = user.first_name if user and user.first_name else ""
    name_part = f", {name}" if name else ""

    welcome = await message.answer(
        f"""
👋 Вітаємо{name_part}!
Ми підготували для вас найкращі акції сьогодні.
Оберіть товар нижче та оформіть замовлення у кілька кліків ⬇️
        """.strip()
    )

    remember_welcome_message(message.chat.id, welcome.message_id)

    # 🔥 ВАЖНО: берём ТОЛЬКО из cache
    products = product_service.get_products()

    if not products:
        await message.answer("Наразі немає доступних товарів. Завітайте пізніше!")
        return

    await asyncio.sleep(1.0)

    reset_product_cards(message.chat.id)

    for product in products:
        msg = await _send_product_card(message, product)
        remember_product_card(message.chat.id, product, msg.message_id)

"""Handlers related to the /start command."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.buy import build_product_caption, remember_product_card, reset_product_cards
from services.product_service import ProductService, Product
from services.user_service import UserService
from handlers.buy import remember_welcome_message


router = Router()


async def _send_product_card(message: Message, product: Product) -> Message:
    """Send a single product card."""
    caption = build_product_caption(product)

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Купити", callback_data=f"buy:{product.id}")

    sent_message = await message.answer_photo(
        photo=product.photo_url,
        caption=caption,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML",
    )

    return sent_message


@router.message(CommandStart())
async def start_handler(
    message: Message, product_service: ProductService, user_service: UserService
) -> None:

    user = message.from_user

    # --- Фоновий запис користувача ---
    if user is not None:
        asyncio.create_task(
            user_service.ensure_user_record(
                user_id=user.id,
                chat_id=message.chat.id,
                username=user.username,
                first_name=user.first_name,
                created_at=datetime.now(timezone.utc),
            )
        )

    # --- Імʼя ---
    name = user.first_name if user and user.first_name else ""
    name_part = f", {name}" if name else ""

    # --- МИТТЄВА відповідь (ВАЖНО ДЛЯ WEBHOOK) ---
    welcome_msg = await message.answer(
        f"""
👋 Вітаємо{name_part}!
Ми підготували для вас найкращі акції сьогодні.
Оберіть товар нижче та оформіть замовлення у кілька кліків ⬇️
        """.strip()
    )

    remember_welcome_message(message.chat.id, welcome_msg.message_id)

    # --- ВЕСЬ ПОКАЗ ТОВАРІВ У ФОН ---
    async def send_products():
        products = await product_service.get_products()

        if not products:
            await message.answer("Наразі немає доступних товарів. Завітайте пізніше!")
            return

        reset_product_cards(message.chat.id)

        for product in products:
            sent_message = await _send_product_card(message, product)
            remember_product_card(message.chat.id, product, sent_message.message_id)

    asyncio.create_task(send_products())


"""Handlers related to the /start command."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.product_service import ProductService, Product
from services.user_service import UserService

router = Router()


async def _send_product_card(message: Message, product: Product) -> None:
    """Send a single product card."""
    caption = (
        f"<b>{product.name}</b>\n"
        f"{product.description}\n\n"
        f"Цена: {product.price}"
    )

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Купить", callback_data=f"buy:{product.id}")

    await message.answer_photo(
        photo=product.photo_url, caption=caption, reply_markup=keyboard.as_markup()
    )


@router.message(CommandStart())
async def start_handler(
    message: Message, product_service: ProductService, user_service: UserService
) -> None:
    """Entry point for new users with dependency injection."""

    user = message.from_user

    # --- Фоновая запись пользователя в Google ---
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

    # --- Определяем имя для приветствия ---
    if user:
        name = user.first_name or (f"@{user.username}" if user.username else "")
    else:
        name = ""

    name_part = f", {name}" if name else ""

    # --- Мгновенное приветствие ---
    await message.answer(
        f"""
👋 Добро пожаловать{name_part}!
Мы подготовили для вас лучшие акции сегодня.
Выберите товар ниже и оформите заказ в несколько кликов ⬇️
        """.strip()
    )

    # --- Получаем товары ---
    products = await product_service.get_products(limit=3)

    if not products:
        await message.answer("Пока нет доступных товаров. Загляните позже!")
        return

    # --- Задержка перед показом товаров ---
    await asyncio.sleep(1.5)

    # --- Отправка карточек товаров ---
    for product in products:
        await _send_product_card(message, product)


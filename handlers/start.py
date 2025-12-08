"""Handlers related to the /start command."""
from __future__ import annotations

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
    if user is not None:
        await user_service.ensure_user_record(
            user_id=user.id,
            chat_id=message.chat.id,
            username=user.username,
            first_name=user.first_name,
            created_at=datetime.now(timezone.utc),
        )

    await message.answer(
        """
👋 Добро пожаловать!
Мы подготовили для вас лучшие акции сегодня.
Выберите товар ниже и оформите заказ в несколько кликов ⬇️
        """.strip()
    )

    products = await product_service.get_products(limit=3)

    if not products:
        await message.answer("Пока нет доступных товаров. Загляните позже!")
        return

    for product in products:
        await _send_product_card(message, product)

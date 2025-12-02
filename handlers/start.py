"""Handlers related to the /start command."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from services.product_service import ProductService, Product

router = Router()


async def _send_product_card(message: Message, product: Product) -> None:
    """Send a single product card."""
    caption = (
        f"<b>{product.name}</b>\n"
        f"{product.description}\n\n"
        f"Цена: {product.price}"
    )

    await message.answer_photo(photo=product.photo_url, caption=caption)


@router.message(CommandStart())
async def start_handler(message: Message, product_service: ProductService) -> None:
    """Entry point for new users with dependency injection."""

    # Загружаем 3 товара
    products = await product_service.get_products(limit=3)

    if not products:
        await message.answer("Пока нет доступных товаров. Загляните позже!")
        return

    # Отправляем товары один за другим
    for product in products:
        await _send_product_card(message, product)

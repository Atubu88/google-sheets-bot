"""Handlers related to the /start command."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from services.product_service import ProductService

router = Router()


async def _send_product_card(message: Message, service: ProductService) -> None:
    product = await service.get_first_product()
    if not product:
        await message.answer("Пока нет доступных товаров. Загляните позже!")
        return

    caption = f"<b>{product.name}</b>\n{product.description}\n\nЦена: {product.price}"
    await message.answer_photo(photo=product.photo_url, caption=caption)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    """Entry point for new users."""

    product_service: ProductService = message.bot["product_service"]
    await _send_product_card(message, product_service)

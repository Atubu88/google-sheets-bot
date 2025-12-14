"""APScheduler job for automatic promo broadcasting."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

from handlers.buy import remember_product_card, reset_product_cards, _build_buy_keyboard, _build_product_caption
from services.product_service import ProductService
from services.promo_settings_service import PromoSettingsService
from services.user_service import UserService

logger = logging.getLogger(__name__)


async def _send_products_to_chat(bot: Bot, chat_id: int, products) -> None:
    reset_product_cards(chat_id)
    for product in products:
        message = await bot.send_photo(
            chat_id=chat_id,
            photo=product.photo_url,
            caption=_build_product_caption(product),
            parse_mode="HTML",
            reply_markup=_build_buy_keyboard(product),
        )
        remember_product_card(chat_id, product, message.message_id)


async def promo_tick(
    bot: Bot,
    product_service: ProductService,
    user_service: UserService,
    promo_settings_service: PromoSettingsService,
) -> None:
    """Periodic job that checks settings and broadcasts promo products."""

    now = datetime.now(timezone.utc)

    try:
        settings = await promo_settings_service.get_settings()
    except Exception:
        logger.exception("Failed to read promo settings")
        return

    if not promo_settings_service.should_send_now(settings, now):
        return

    try:
        products = await product_service.get_products()
    except Exception:
        logger.exception("Failed to load products for promo sending")
        return

    if not products:
        logger.info("Promo tick skipped: no products available")
        return

    try:
        chat_ids = await user_service.get_chat_ids()
    except Exception:
        logger.exception("Failed to load chat IDs for promo sending")
        return

    if not chat_ids:
        logger.info("Promo tick skipped: no users to notify")
        return

    logger.info("Starting promo broadcast to %s chats", len(chat_ids))

    send_tasks = [
        _send_products_to_chat(bot, chat_id, products) for chat_id in chat_ids
    ]

    await asyncio.gather(*send_tasks, return_exceptions=True)

    try:
        await promo_settings_service.update_last_sent_at(now)
    except Exception:
        logger.exception("Failed to update last_sent_at after promo broadcast")
    else:
        logger.info("Promo broadcast finished and timestamp updated")

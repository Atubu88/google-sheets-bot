"""APScheduler job for automatic promo broadcasting."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot

from handlers.buy import remember_product_card, reset_product_cards, _build_buy_keyboard, build_product_caption
from services.product_service import ProductService
from services.promo_settings_service import PromoSettingsService
from services.user_service import UserService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PromoBroadcastResult:
    status: str
    chats: int
    products: int


async def _send_products_to_chat(bot: Bot, chat_id: int, products) -> None:
    reset_product_cards(chat_id)
    for product in products:
        message = await bot.send_photo(
            chat_id=chat_id,
            photo=product.photo_url,
            caption=build_product_caption(product),
            parse_mode="HTML",
            reply_markup=_build_buy_keyboard(product),
        )
        remember_product_card(chat_id, product, message.message_id)


async def broadcast_promo(
    bot: Bot,
    product_service: ProductService,
    user_service: UserService,
) -> PromoBroadcastResult:
    """Send promo products to all known chat IDs without side-effects."""

    try:
        products = await product_service.get_products()
    except Exception:
        logger.exception("Failed to load products for promo sending")
        return PromoBroadcastResult(status="error", chats=0, products=0)

    if not products:
        logger.info("Promo broadcast skipped: no products available")
        return PromoBroadcastResult(status="no_products", chats=0, products=0)

    try:
        chat_ids = await user_service.get_chat_ids()
    except Exception:
        logger.exception("Failed to load chat IDs for promo sending")
        return PromoBroadcastResult(
            status="error",
            chats=0,
            products=len(products),
        )

    if not chat_ids:
        logger.info("Promo broadcast skipped: no users to notify")
        return PromoBroadcastResult(
            status="no_chats",
            chats=0,
            products=len(products),
        )

    logger.info("Starting promo broadcast to %s chats", len(chat_ids))

    send_tasks = [
        _send_products_to_chat(bot, chat_id, products) for chat_id in chat_ids
    ]

    results = await asyncio.gather(*send_tasks, return_exceptions=True)
    failures = [result for result in results if isinstance(result, Exception)]

    if failures:
        logger.warning("Promo broadcast finished with %s failures", len(failures))
        return PromoBroadcastResult(
            status="error",
            chats=len(chat_ids),
            products=len(products),
        )

    logger.info("Promo broadcast finished successfully")
    return PromoBroadcastResult(
        status="sent",
        chats=len(chat_ids),
        products=len(products),
    )


async def promo_tick(
    bot: Bot,
    product_service: ProductService,
    user_service: UserService,
    promo_settings_service: PromoSettingsService,
) -> None:
    """Periodic job that checks settings and broadcasts promo products."""

    now = datetime.now(ZoneInfo("Europe/Kyiv"))

    try:
        settings = await promo_settings_service.get_settings()
    except Exception:
        logger.exception("Failed to read promo settings")
        return

    if not promo_settings_service.should_send_now(settings, now):
        return

    result = await broadcast_promo(bot, product_service, user_service)

    if result.status != "sent":
        logger.info("Promo tick finished with status: %s", result.status)
        return

    try:
        await promo_settings_service.update_last_sent_date(now.date())
    except Exception:
        logger.exception("Failed to update last_sent_date after promo broadcast")
    else:
        logger.info("Promo broadcast finished and date updated")

"""APScheduler job for automatic promo broadcasting."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from handlers.buy import remember_product_card, reset_product_cards, _build_buy_keyboard, build_product_caption
from services.product_service import ProductService
from services.promo_settings_service import PromoSettingsService
from services.safe_sender import SafeSender
from services.user_service import UserService

logger = logging.getLogger(__name__)
_broadcast_lock = asyncio.Lock()


@dataclass(slots=True)
class PromoBroadcastResult:
    status: str
    chats: int
    products: int
    success: int = 0
    forbidden: int = 0
    temporary_errors: int = 0
    permanent_errors: int = 0


def _is_retryable_error(error: Exception) -> bool:
    return isinstance(error, (TelegramRetryAfter, TelegramServerError, TelegramNetworkError))


def _iter_chunks(items: list[int], chunk_size: int):
    for index in range(0, len(items), chunk_size):
        yield items[index:index + chunk_size]


async def _send_products_to_chat(
    safe_sender: SafeSender,
    chat_id: int,
    products,
) -> bool:
    reset_product_cards(chat_id)
    for product in products:
        message = await safe_sender.send_photo(
            chat_id=chat_id,
            photo=product.photo_url,
            caption=build_product_caption(product),
            parse_mode="HTML",
            reply_markup=_build_buy_keyboard(product),
        )
        if message is None:
            return False
        remember_product_card(chat_id, product, message.message_id)
    return True


async def _send_products_with_retry(
    safe_sender: SafeSender,
    chat_id: int,
    products,
    max_attempts: int = 3,
) -> str:
    for attempt in range(1, max_attempts + 1):
        try:
            success = await _send_products_to_chat(safe_sender, chat_id, products)
            if success:
                return "success"

            logger.info("Promo send forbidden for chat_id=%s", chat_id)
            return "forbidden"
        except Exception as exc:
            retryable = _is_retryable_error(exc)
            logger.warning(
                "Promo send failed (chat_id=%s, attempt=%s/%s, retryable=%s)",
                chat_id,
                attempt,
                max_attempts,
                retryable,
                exc_info=True,
            )
            if retryable and attempt < max_attempts:
                if isinstance(exc, TelegramRetryAfter):
                    await asyncio.sleep(min(max(exc.retry_after, 0), 5))
                else:
                    await asyncio.sleep(0.5 * attempt)
                continue
            return "temporary_error" if retryable else "permanent_error"
    return "temporary_error"


async def broadcast_promo(
    safe_sender: SafeSender,
    product_service: ProductService,
    user_service: UserService,
) -> PromoBroadcastResult:
    """Send promo products to all known chat IDs without side-effects."""

    try:
        await asyncio.wait_for(_broadcast_lock.acquire(), timeout=0.01)
    except TimeoutError:
        logger.warning("Promo broadcast skipped: previous run is still in progress")
        return PromoBroadcastResult(status="busy", chats=0, products=0)

    try:
        return await _broadcast_promo_impl(safe_sender, product_service, user_service)
    finally:
        _broadcast_lock.release()


async def _broadcast_promo_impl(
    safe_sender: SafeSender,
    product_service: ProductService,
    user_service: UserService,
) -> PromoBroadcastResult:
    """Internal broadcast implementation guarded by a single-run lock."""

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

    max_parallel_sends = 20
    batch_pause_seconds = 0.05
    success = 0
    forbidden = 0
    temporary_errors = 0
    permanent_errors = 0

    for batch_no, batch_chat_ids in enumerate(_iter_chunks(chat_ids, max_parallel_sends), start=1):
        results = await asyncio.gather(
            *(_send_products_with_retry(safe_sender, chat_id, products) for chat_id in batch_chat_ids)
        )
        success += sum(1 for result in results if result == "success")
        forbidden += sum(1 for result in results if result == "forbidden")
        temporary_errors += sum(1 for result in results if result == "temporary_error")
        permanent_errors += sum(1 for result in results if result == "permanent_error")
        logger.info(
            "Promo batch #%s done: batch_size=%s, total_progress=%s/%s",
            batch_no,
            len(batch_chat_ids),
            success + forbidden + temporary_errors + permanent_errors,
            len(chat_ids),
        )
        if batch_pause_seconds > 0:
            await asyncio.sleep(batch_pause_seconds)

    flushed_forbidden = await safe_sender.flush_pending_forbidden_statuses(
        max_updates=30,
        pause_seconds=0.05,
    )
    pending_forbidden = await safe_sender.pending_forbidden_count()

    status = "sent_with_failures" if (temporary_errors or permanent_errors) else "sent"

    logger.info(
        "Promo broadcast summary: status=%s total=%s, success=%s, forbidden=%s, temporary_errors=%s, permanent_errors=%s, forbidden_flushed=%s",
        status,
        len(chat_ids),
        success,
        forbidden,
        temporary_errors,
        permanent_errors,
        flushed_forbidden,
    )
    if pending_forbidden:
        logger.info("Forbidden status queue still has %s users for next flush", pending_forbidden)

    return PromoBroadcastResult(
        status=status,
        chats=len(chat_ids),
        products=len(products),
        success=success,
        forbidden=forbidden,
        temporary_errors=temporary_errors,
        permanent_errors=permanent_errors,
    )


async def promo_tick(
    safe_sender: SafeSender,
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

    result = await broadcast_promo(safe_sender, product_service, user_service)

    if result.status not in {"sent", "sent_with_failures"}:
        logger.info("Promo tick finished with status: %s", result.status)
        return

    try:
        await promo_settings_service.update_last_sent_date(now.date())
    except Exception:
        logger.exception("Failed to update last_sent_date after promo broadcast")
    else:
        logger.info("Promo broadcast finished and date updated")

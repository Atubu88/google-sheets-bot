"""Main entrypoint for the Telegram bot."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import get_settings
from handlers import start
from handlers import buy
from services.product_service import ProductService
from services.sheets_client import SheetsClient
from services.user_service import UserService
from middlewares.deps import DependencyMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_dependencies() -> dict[str, object]:
    settings = get_settings()
    product_sheets_client = SheetsClient(
        service_account_file=settings.service_account_file,
        spreadsheet_id=settings.spreadsheet_id,
        worksheet_name=settings.worksheet_name,
    )
    user_sheets_client = SheetsClient(
        service_account_file=settings.service_account_file,
        spreadsheet_id=settings.spreadsheet_id,
        worksheet_name=settings.users_worksheet,
    )

    product_service = ProductService(product_sheets_client)
    user_service = UserService(user_sheets_client)
    return {
        "settings": settings,
        "product_service": product_service,
        "user_service": user_service,
    }


async def main() -> None:
    deps = build_dependencies()
    settings = deps["settings"]
    product_service = deps["product_service"]
    user_service = deps["user_service"]

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher(storage=MemoryStorage())

    # DI middleware
    dp.update.middleware(DependencyMiddleware(
        product_service=product_service,
        user_service=user_service
    ))

    dp.include_router(start.router)
    dp.include_router(buy.router)

    logger.info("Starting background cache updater")
    cache_task = asyncio.create_task(
        product_service.background_updater(
            settings.cache_update_interval_minutes
        )
    )

    logger.info("Starting bot")
    try:
        await dp.start_polling(bot)
    finally:
        cache_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cache_task


if __name__ == "__main__":
    asyncio.run(main())

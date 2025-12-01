"""Main entrypoint for the Telegram bot."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import get_settings
from handlers import start
from services.product_service import ProductService
from services.sheets_client import SheetsClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_dependencies() -> dict[str, object]:
    settings = get_settings()
    sheets_client = SheetsClient(
        service_account_file=settings.service_account_file,
        spreadsheet_id=settings.spreadsheet_id,
        worksheet_name=settings.worksheet_name,
    )
    product_service = ProductService(sheets_client)
    return {"settings": settings, "product_service": product_service}


async def main() -> None:
    deps = build_dependencies()
    settings = deps["settings"]

    bot = Bot(token=settings.bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())

    # Inject dependencies into bot context for handlers.
    bot["product_service"] = deps["product_service"]

    dp.include_router(start.router)

    logger.info("Starting bot")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

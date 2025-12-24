"""Main entrypoint for the Telegram bot."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import get_settings
from handlers import buy
from handlers import order
from handlers import start
from handlers import admin
from middlewares.deps import DependencyMiddleware
from services.crm_client import LPCRMClient
from services.customer_service import CustomerService
from services.product_service import ProductService
from services.promo_scheduler import promo_tick
from services.promo_settings_service import PromoSettingsService
from services.settings_service import SettingsService
from services.sheets_client import SheetsClient
from services.user_service import UserService

def configure_logging(level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(level)

    # Удаляем любые старые хендлеры, чтобы избежать дублирования и конфликтов
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Создаём handler, который пишет в stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    root.addHandler(handler)

    # Настраиваем уровни библиотек
    logging.getLogger("aiogram").setLevel(level)
    logging.getLogger("aiohttp").setLevel(level)

    return logging.getLogger(__name__)


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
    promo_settings_client = SheetsClient(
        service_account_file=settings.service_account_file,
        spreadsheet_id=settings.spreadsheet_id,
        worksheet_name=settings.promo_settings_worksheet,
    )
    promo_settings_service = PromoSettingsService(promo_settings_client)
    customer_service = CustomerService(settings.customers_db_path)
    crm_client = LPCRMClient(
        api_key=settings.crm_api_key,
        base_url=settings.crm_base_url,
        office_id=settings.crm_office_id,
    )
    settings_service = SettingsService(settings.customers_db_path)
    return {
        "settings": settings,
        "product_service": product_service,
        "user_service": user_service,
        "promo_settings_service": promo_settings_service,
        "customer_service": customer_service,
        "crm_client": crm_client,
        "settings_service": settings_service,
    }

logger = configure_logging()

async def main() -> None:
    deps = build_dependencies()
    settings = deps["settings"]
    product_service = deps["product_service"]
    user_service = deps["user_service"]
    promo_settings_service = deps["promo_settings_service"]
    customer_service = deps["customer_service"]
    crm_client = deps["crm_client"]
    settings_service = deps["settings_service"]

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher(storage=MemoryStorage())

    # DI middleware
    dp.update.middleware(DependencyMiddleware(
        product_service=product_service,
        user_service=user_service,
        customer_service=customer_service,
        crm_client=crm_client,
        settings_service=settings_service,
    ))

    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(order.router)
    dp.include_router(admin.router)

    logger.info("Starting background cache updater")
    cache_task = asyncio.create_task(
        product_service.background_updater(
            settings.cache_update_interval_minutes
        )
    )

    logger.info("Starting bot")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        promo_tick,
        "interval",
        minutes=5,
        args=(bot, product_service, user_service, promo_settings_service),
    )
    scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        cache_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cache_task


if __name__ == "__main__":
    asyncio.run(main())

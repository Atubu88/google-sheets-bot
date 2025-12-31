"""Main entrypoint for the Telegram bot (Webhook version)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from fastapi import FastAPI, Request
import uvicorn

from config import get_settings
from handlers import buy, order, start, admin
from middlewares.deps import DependencyMiddleware
from services.crm_client import LPCRMClient
from services.customer_service import CustomerService
from services.product_service import ProductService
from services.promo_scheduler import promo_tick
from services.promo_settings_service import PromoSettingsService
from services.settings_service import SettingsService
from services.sheets_client import SheetsClient
from services.user_service import UserService


# --------------------------------------------------
# LOGGING
# --------------------------------------------------

def configure_logging(level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root.addHandler(handler)

    logging.getLogger("aiogram").setLevel(level)
    logging.getLogger("aiohttp").setLevel(level)

    return logging.getLogger(__name__)


logger = configure_logging()


# --------------------------------------------------
# DEPENDENCIES
# --------------------------------------------------

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
    promo_settings_client = SheetsClient(
        service_account_file=settings.service_account_file,
        spreadsheet_id=settings.spreadsheet_id,
        worksheet_name=settings.promo_settings_worksheet,
    )

    return {
        "settings": settings,
        "product_service": ProductService(product_sheets_client),
        "user_service": UserService(user_sheets_client),
        "promo_settings_service": PromoSettingsService(promo_settings_client),
        "customer_service": CustomerService(settings.customers_db_path),
        "crm_client": LPCRMClient(
            api_key=settings.crm_api_key,
            base_url=settings.crm_base_url,
            office_id=settings.crm_office_id,
        ),
        "settings_service": SettingsService(settings.customers_db_path),
    }


# --------------------------------------------------
# FASTAPI APP
# --------------------------------------------------

app = FastAPI()


@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = await request.json()
    await app.state.dp.feed_raw_update(app.state.bot, update)
    return {"ok": True}


# --------------------------------------------------
# MAIN
# --------------------------------------------------

async def startup() -> None:
    deps = build_dependencies()
    settings = deps["settings"]

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Middleware
    dp.update.middleware(
        DependencyMiddleware(
            product_service=deps["product_service"],
            user_service=deps["user_service"],
            customer_service=deps["customer_service"],
            crm_client=deps["crm_client"],
            settings_service=deps["settings_service"],
        )
    )

    # Routers
    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(order.router)
    dp.include_router(admin.router)

    # Attach to FastAPI
    app.state.bot = bot
    app.state.dp = dp

    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        promo_tick,
        "interval",
        minutes=5,
        args=(
            bot,
            deps["product_service"],
            deps["user_service"],
            deps["promo_settings_service"],
        ),
    )
    scheduler.start()
    app.state.scheduler = scheduler

    # Background cache updater
    cache_task = asyncio.create_task(
        deps["product_service"].background_updater(
            settings.cache_update_interval_minutes
        )
    )
    app.state.cache_task = cache_task

    # Webhook (only on Railway / prod)
    webhook_base_url = os.getenv("WEBHOOK_BASE_URL")
    if webhook_base_url:
        webhook_url = f"{webhook_base_url}/webhook"
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(webhook_url)
        logger.info("Webhook set to %s", webhook_url)
    else:
        logger.info("WEBHOOK_BASE_URL not set — local mode")


@app.on_event("startup")
async def on_startup():
    await startup()


@app.on_event("shutdown")
async def on_shutdown():
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)

    cache_task = getattr(app.state, "cache_task", None)
    if cache_task:
        cache_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cache_task


# --------------------------------------------------
# ENTRYPOINT
# --------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )

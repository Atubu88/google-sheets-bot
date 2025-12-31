"""Main entrypoint for the Telegram bot (Webhook + Railway)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from fastapi import FastAPI, Request

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------
# FASTAPI APP
# --------------------------------------------------

app = FastAPI()


@app.post("/webhook")
async def telegram_webhook(request: Request):
    logger.info("📩 Incoming webhook")
    data = await request.json()
    update = Update.model_validate(data)
    await app.state.dp.feed_update(app.state.bot, update)
    return {"ok": True}


# --------------------------------------------------
# STARTUP
# --------------------------------------------------

@app.on_event("startup")
async def on_startup():
    settings = get_settings()

    # ---- BOT ----
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # ---- DEPENDENCIES ----
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

    product_service = ProductService(product_sheets_client)
    user_service = UserService(user_sheets_client)
    promo_settings_service = PromoSettingsService(promo_settings_client)
    customer_service = CustomerService(settings.customers_db_path)
    crm_client = LPCRMClient(
        api_key=settings.crm_api_key,
        base_url=settings.crm_base_url,
        office_id=settings.crm_office_id,
    )
    settings_service = SettingsService(settings.customers_db_path)

    dp.update.middleware(
        DependencyMiddleware(
            product_service=product_service,
            user_service=user_service,
            customer_service=customer_service,
            crm_client=crm_client,
            settings_service=settings_service,
        )
    )

    # ---- ROUTERS ----
    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(order.router)
    dp.include_router(admin.router)

    # ---- STORE ----
    app.state.bot = bot
    app.state.dp = dp

    # ---- SCHEDULER ----
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        promo_tick,
        "interval",
        minutes=5,
        args=(bot, product_service, user_service, promo_settings_service),
    )
    scheduler.start()
    app.state.scheduler = scheduler

    # ---- CACHE UPDATER ----
    cache_task = asyncio.create_task(
        product_service.background_updater(
            settings.cache_update_interval_minutes
        )
    )
    app.state.cache_task = cache_task

    # ---- WEBHOOK ----
    webhook_base_url = os.getenv("WEBHOOK_BASE_URL")
    if not webhook_base_url:
        raise RuntimeError("WEBHOOK_BASE_URL is not set (Railway env var)")

    webhook_url = f"{webhook_base_url}/webhook"
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(webhook_url)

    logger.info("✅ Webhook set to %s", webhook_url)


# --------------------------------------------------
# SHUTDOWN
# --------------------------------------------------

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

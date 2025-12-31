"""Main entrypoint for the Telegram bot (Webhook + Railway, STABLE)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import socket
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
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


# ✅ Healthcheck (Railway)
@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)

    # 🔥 НЕ ЖДЁМ ОБРАБОТКУ
    asyncio.create_task(
        app.state.dp.feed_update(app.state.bot, update)
    )

    # ⚡ МГНОВЕННЫЙ ОТВЕТ TELEGRAM
    return {"ok": True}



# --------------------------------------------------
# STARTUP
# --------------------------------------------------

@app.on_event("startup")
async def on_startup():
    settings = get_settings()

    import socket
    import aiohttp
    from aiogram.client.session.aiohttp import AiohttpSession

    connector = aiohttp.TCPConnector(
        family=socket.AF_INET  # ⬅️ ЖЁСТКО IPv4
    )

    session = AiohttpSession(
        timeout=30,
        connector=connector,
    )

    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # ---- SERVICES ----
    product_service = ProductService(
        SheetsClient(
            settings.service_account_file,
            settings.spreadsheet_id,
            settings.worksheet_name,
        )
    )

    user_service = UserService(
        SheetsClient(
            settings.service_account_file,
            settings.spreadsheet_id,
            settings.users_worksheet,
        )
    )

    promo_settings_service = PromoSettingsService(
        SheetsClient(
            settings.service_account_file,
            settings.spreadsheet_id,
            settings.promo_settings_worksheet,
        )
    )

    customer_service = CustomerService(settings.customers_db_path)

    crm_client = LPCRMClient(
        api_key=settings.crm_api_key,
        base_url=settings.crm_base_url,
        office_id=settings.crm_office_id,
    )

    settings_service = SettingsService(settings.customers_db_path)

    # ---- MIDDLEWARE ----
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

    # ---- CACHE ----
    cache_task = asyncio.create_task(
        product_service.background_updater(
            settings.cache_update_interval_minutes
        )
    )
    app.state.cache_task = cache_task

    # ---- WEBHOOK (NON-BLOCKING) ----
    webhook_base = os.getenv("WEBHOOK_BASE_URL")

    if not webhook_base:
        raise RuntimeError("WEBHOOK_BASE_URL is not set")

    webhook_url = f"{webhook_base}/webhook"

    async def ensure_webhook():
        try:
            await bot.set_webhook(webhook_url)
            logger.info("✅ Webhook set to %s", webhook_url)
        except Exception as e:
            logger.error("⚠️ Webhook setup failed: %s", e)

    asyncio.create_task(ensure_webhook())

    logger.info("✅ Startup completed")


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

    logger.info("🛑 Shutdown completed")


# --------------------------------------------------
# ENTRYPOINT
# --------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
    )

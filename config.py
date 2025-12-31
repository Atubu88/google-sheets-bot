"""Project configuration using environment variables.

Provides a simple Settings class that loads Bot and Google Sheets
configuration from a ``.env`` file or the process environment.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    """Typed configuration for the application."""
    port: int = Field(8000, validation_alias="PORT")
    bot_token: str = Field(..., validation_alias="BOT_TOKEN")
    spreadsheet_id: str = Field(..., validation_alias="GOOGLE_SHEETS_ID")
    worksheet_name: str = Field("products", validation_alias="GOOGLE_SHEET_NAME")
    users_worksheet: str = Field("users", validation_alias="GOOGLE_USERS_SHEET")
    promo_settings_worksheet: str = Field(
        "promo_settings", validation_alias="GOOGLE_PROMO_SETTINGS_SHEET"
    )
    orders_worksheet: str = Field("orders", validation_alias="GOOGLE_ORDERS_SHEET")
    service_account_file: Path = Field(
        Path("service_account.json"), validation_alias="GOOGLE_SERVICE_ACCOUNT_FILE"
    )
    cache_update_interval_minutes: int = Field(
        5, validation_alias="CACHE_UPDATE_INTERVAL_MINUTES"
    )
    crm_api_key: str = Field(..., validation_alias="CRM_API_KEY")
    crm_base_url: str = Field(..., validation_alias="CRM_API_BASE_URL")
    crm_office_id: int = Field(..., validation_alias="CRM_OFFICE_ID")
    customers_db_path: Path = Field(
        Path("customers.db"), validation_alias="CUSTOMERS_DB_PATH"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()

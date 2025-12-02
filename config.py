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

    bot_token: str = Field(..., validation_alias="BOT_TOKEN")
    spreadsheet_id: str = Field(..., validation_alias="GOOGLE_SHEETS_ID")
    worksheet_name: str = Field("Products", validation_alias="GOOGLE_SHEET_NAME")
    service_account_file: Path = Field(
        Path("service_account.json"), validation_alias="GOOGLE_SERVICE_ACCOUNT_FILE"
    )
    cache_update_interval_minutes: int = Field(
        5, validation_alias="CACHE_UPDATE_INTERVAL_MINUTES"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()

"""Async settings storage backed by SQLite."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import aiosqlite


class SettingsService:
    """Persist and retrieve bot settings using SQLite."""

    def __init__(self, db_path: str | Path = "customers.db"):
        self._db_path = Path(db_path)

    async def get(self, key: str) -> Optional[str]:
        """Return the stored value for *key*, or ``None`` if not set."""

        async with aiosqlite.connect(self._db_path) as db:
            await self._ensure_table(db)
            async with db.execute(
                "SELECT value FROM bot_settings WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def set(self, key: str, value: str) -> None:
        """Persist *value* for *key* in the settings table."""

        async with aiosqlite.connect(self._db_path) as db:
            await self._ensure_table(db)
            await db.execute(
                """
                INSERT INTO bot_settings(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
            await db.commit()

    async def _ensure_table(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        await db.commit()

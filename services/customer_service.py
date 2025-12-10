"""SQLite-backed service for storing customer delivery details."""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class CustomerService:
    """Persist customer contact and delivery info in SQLite."""

    def __init__(self, db_path: str | Path = "customers.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def get_customer(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Return a single customer row as a dict or ``None`` if absent."""

        await self._ensure_initialized()
        row = await self._execute(
            "SELECT telegram_id, name, phone, city, post_office, updated_at "
            "FROM customers WHERE telegram_id = ?",
            (telegram_id,),
            fetchone=True,
        )
        return dict(row) if row else None

    async def create_customer(
        self,
        telegram_id: int,
        name: str,
        phone: str,
        city: str,
        post_office: str,
    ) -> None:
        """Insert a new customer row."""

        await self._ensure_initialized()
        await self._execute(
            """
            INSERT INTO customers (telegram_id, name, phone, city, post_office, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_id,
                name,
                phone,
                city,
                post_office,
                self._now(),
            ),
        )

    async def update_customer(
        self,
        telegram_id: int,
        name: str,
        phone: str,
        city: str,
        post_office: str,
    ) -> None:
        """Update existing customer data by telegram_id."""

        await self._ensure_initialized()
        await self._execute(
            """
            UPDATE customers
            SET name = ?, phone = ?, city = ?, post_office = ?, updated_at = ?
            WHERE telegram_id = ?
            """,
            (
                name,
                phone,
                city,
                post_office,
                self._now(),
                telegram_id,
            ),
        )

    async def save_or_update(
        self,
        telegram_id: int,
        name: str,
        phone: str,
        city: str,
        post_office: str,
    ) -> None:
        """Create or update a customer record in one call."""

        existing = await self.get_customer(telegram_id)
        if existing:
            await self.update_customer(telegram_id, name, phone, city, post_office)
        else:
            await self.create_customer(telegram_id, name, phone, city, post_office)

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._create_table)
            self._initialized = True

    def _create_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    telegram_id INTEGER PRIMARY KEY,
                    name TEXT,
                    phone TEXT,
                    city TEXT,
                    post_office TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.commit()

    async def _execute(
        self, query: str, params: tuple[Any, ...], *, fetchone: bool = False
    ) -> Any:
        def inner() -> Any:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(query, params)
                conn.commit()
                return cursor.fetchone() if fetchone else cursor.fetchall()

        return await asyncio.to_thread(inner)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

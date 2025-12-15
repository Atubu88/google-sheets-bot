"""Business logic for working with products and caching layer."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from .sheets_client import SheetRow, SheetsClient


@dataclass(slots=True)
class Product:
    id: str
    name: str
    short_desc: str
    description: str
    photo_url: str
    price: str


class ProductService:
    """High-level API for product operations with in-memory caching."""

    def __init__(self, sheets_client: SheetsClient):
        self._sheets_client = sheets_client
        self._cache: list[Product] = []
        self._last_updated: datetime | None = None
        self._update_lock = asyncio.Lock()
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def last_updated(self) -> datetime | None:
        """Return the UTC datetime of the last successful cache refresh."""

        return self._last_updated

    async def get_first_product(self) -> Optional[Product]:
        """Return the first available product or ``None`` if the sheet is empty."""

        products = await self.get_products(limit=1)
        return products[0] if products else None

    async def get_products(self, limit: int | None = None) -> List[Product]:
        """Return cached products, optionally limited to the first ``limit`` items."""

        if not self._cache:
            await self.update_cache()

        if limit is None:
            return list(self._cache)

        return self._cache[:limit]

    async def update_cache(self) -> None:
        """Refresh the in-memory cache from Google Sheets."""

        async with self._update_lock:
            try:
                rows = await self._sheets_client.fetch_rows()
                self._cache = [self._map_row_to_product(row) for row in rows]
                self._last_updated = datetime.now(timezone.utc)
                self._logger.info(
                    "Product cache refreshed: %s items at %s",
                    len(self._cache),
                    self._last_updated.isoformat(),
                )
            except Exception:
                self._logger.exception("Failed to refresh product cache")
                raise

    async def background_updater(
        self,
        interval_minutes: int,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """
        Periodically refresh the cache, restarting on failures.

        Args:
            interval_minutes: Interval between updates.
            stop_event: Optional event to signal graceful shutdown.
        """

        wait_seconds = max(interval_minutes, 1) * 60

        while True:
            try:
                await self.update_cache()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._logger.exception("Background updater iteration failed")

            try:
                if stop_event is not None:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
                    self._logger.info("Stopping background cache updater")
                    return
                await asyncio.sleep(wait_seconds)
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                # Normal path when timeout expires; continue to next iteration.
                continue

    def _map_row_to_product(self, row: SheetRow) -> Product:
        return Product(
            id=row.id,
            name=row.name,
            short_desc=row.short_desc,
            description=row.description,
            photo_url=row.photo_url,
            price=row.price,
        )

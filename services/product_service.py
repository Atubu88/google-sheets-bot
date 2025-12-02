"""Business logic for working with products."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List

from .sheets_client import SheetRow, SheetsClient


@dataclass(slots=True)
class Product:
    id: str
    name: str
    description: str
    photo_url: str
    price: str


class ProductService:
    """High-level API for product operations."""

    def __init__(self, sheets_client: SheetsClient):
        self._sheets_client = sheets_client

    async def get_first_product(self) -> Optional[Product]:
        """Return the first available product or ``None`` if the sheet is empty."""
        rows = await self._sheets_client.fetch_rows()
        if not rows:
            return None
        return self._map_row_to_product(rows[0])

    async def get_products(self, limit: int = 3) -> List[Product]:
        """
        Return first N products from Google Sheets.
        """
        rows = await self._sheets_client.fetch_rows()
        rows = rows[:limit]  # ограничение по количеству
        return [self._map_row_to_product(row) for row in rows]

    def _map_row_to_product(self, row: SheetRow) -> Product:
        return Product(
            id=row.id,
            name=row.name,
            description=row.description,
            photo_url=row.photo_url,
            price=row.price,
        )

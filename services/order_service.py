"""Service layer for creating orders in Google Sheets."""
from __future__ import annotations

from datetime import datetime, timezone

from services.sheets_client import SheetsClient


class OrderService:
    """High-level API for working with orders."""

    def __init__(self, sheets_client: SheetsClient):
        self._sheets_client = sheets_client

    async def append_order(
        self,
        *,
        user_id: int | None,
        chat_id: int,
        product_id: str,
        product_name: str,
        product_price: str,
        phone: str,
        city: str,
        branch: str,
    ) -> None:
        """Append a new order to the worksheet."""

        await self._sheets_client.append_row(
            [
                str(user_id or ""),
                str(chat_id),
                product_id,
                product_name,
                product_price,
                phone,
                city,
                branch,
                datetime.now(timezone.utc).isoformat(),
            ]
        )


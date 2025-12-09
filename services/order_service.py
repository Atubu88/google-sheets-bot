"""Service layer for creating orders in Google Sheets."""
from __future__ import annotations

from datetime import datetime, timezone

from services.sheets_client import SheetsClient


class OrderService:
    """High-level API for working with orders."""

    def __init__(self, sheets_client: SheetsClient):
        self._sheets_client = sheets_client

    async def _get_next_order_id(self) -> str:
        """Compute the next incremental order ID based on existing rows."""

        rows = await self._sheets_client.fetch_raw_rows(skip_header=True)

        last_id = 0
        for row in rows:
            if not row:
                continue

            try:
                order_id = int(row[0])
            except (ValueError, IndexError):
                continue

            last_id = max(last_id, order_id)

        return str(last_id + 1)

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

        order_id = await self._get_next_order_id()
        await self._sheets_client.append_row(
            [
                order_id,
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


"""Service layer for creating orders in Google Sheets."""
from __future__ import annotations

from datetime import datetime, timezone

from services.sheets_client import SheetsClient


class OrderService:
    """High-level API for working with orders."""

    def __init__(self, sheets_client: SheetsClient):
        self._sheets_client = sheets_client

    async def _get_next_order_id(self) -> str:
        rows = await self._sheets_client.fetch_raw_rows(skip_header=True)

        last_id = 0
        for row in rows:
            if row and row[0].isdigit():
                last_id = max(last_id, int(row[0]))

        return str(last_id + 1)

    async def append_order(
        self,
        *,
        user_id: int | None,
        chat_id: int,
        username: str | None,
        first_name: str | None,
        product_id: str,
        product_name: str,
        product_price: str,
        phone: str,
        city: str,
        branch: str,
    ) -> None:

        order_id = await self._get_next_order_id()

        await self._sheets_client.append_row(
            [
                order_id,                # A
                str(user_id or ""),      # B user_id
                username or "",          # C username
                first_name or "",        # D first_name
                phone,                   # E phone
                city,                    # F city
                branch,                  # G np_branch
                product_id,              # H
                product_name,            # I
                product_price,           # J
                datetime.now(timezone.utc).isoformat(),  # K created_at
            ]
        )


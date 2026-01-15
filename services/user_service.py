"""Service for working with Telegram users stored in Google Sheets."""
from __future__ import annotations

from datetime import datetime

from services.sheets_client import SheetsClient


class UserService:
    """High-level operations for persisting and checking users."""

    _status_column_index = 6

    def __init__(self, sheets_client: SheetsClient):
        self._sheets_client = sheets_client

    async def ensure_user_record(
        self,
        *,
        user_id: int,
        chat_id: int,
        username: str | None,
        first_name: str | None,
        created_at: datetime,
    ) -> bool:
        """Ensure a user exists in the worksheet.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            username: Telegram username, may be ``None``.
            first_name: Telegram first name, may be ``None``.
            created_at: Timestamp when the record was created.

        Returns:
            ``True`` if a new record was created, ``False`` otherwise.
        """

        user_id_str = str(user_id)
        existing_row = await self._sheets_client.find_row_index(1, user_id_str)
        if existing_row is not None:
            await self.update_status(user_id, is_active=True)
            return False

        await self._sheets_client.append_row(
            [
                user_id_str,
                str(chat_id),
                username or "",
                first_name or "",
                created_at.isoformat(),
                "active",
            ]
        )
        return True

    async def update_status(self, user_id: int, is_active: bool) -> bool:
        """Update user status in the worksheet."""

        user_id_str = str(user_id)
        row_index = await self._sheets_client.find_row_index(1, user_id_str)
        if row_index is None:
            return False

        status_value = "active" if is_active else "left"
        await self._sheets_client.update_cell(
            row_index,
            self._status_column_index,
            status_value,
        )
        return True

    async def get_statistics(self) -> dict[str, int]:
        """Return overall user statistics based on the worksheet."""

        rows = await self._sheets_client.fetch_raw_rows(skip_header=True)
        total = 0
        active = 0
        left = 0

        for row in rows:
            if not row or not row[0].strip():
                continue
            total += 1
            if len(row) >= self._status_column_index:
                status_value = row[self._status_column_index - 1].strip().lower()
            else:
                status_value = ""
            if status_value == "left":
                left += 1
            else:
                active += 1

        return {
            "total": total,
            "active": active,
            "left": left,
        }

    async def get_chat_ids(self) -> list[int]:
        """Return all chat IDs stored in the worksheet."""

        rows = await self._sheets_client.fetch_raw_rows(skip_header=True)
        chat_ids: list[int] = []

        for row in rows:
            if len(row) < 2:
                continue

            try:
                chat_ids.append(int(row[1]))
            except (TypeError, ValueError):
                continue

        return chat_ids

"""Service for working with Telegram users stored in Google Sheets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from services.sheets_client import SheetsClient


STATUS_COLUMN = 6
USER_ID_COLUMN = 1


@dataclass(slots=True)
class UserStatistics:
    total: int
    active: int
    left: int


class UserService:
    """High-level operations for persisting and checking users."""

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
        row_index = await self._sheets_client.find_row_index(
            USER_ID_COLUMN,
            user_id_str,
        )

        if row_index:
            await self._sheets_client.update_cell(row_index, STATUS_COLUMN, "active")
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

    async def get_chat_ids(self) -> list[int]:
        """Return all chat IDs stored in the worksheet."""

        rows = await self._sheets_client.fetch_raw_rows(skip_header=True)
        chat_ids: list[int] = []

        for row in rows:
            if len(row) < 2:
                continue
            if len(row) >= STATUS_COLUMN:
                status = row[STATUS_COLUMN - 1].strip().lower()
                if status == "left":
                    continue

            try:
                chat_ids.append(int(row[1]))
            except (TypeError, ValueError):
                continue

        return chat_ids

    async def update_status(self, user_id: int, is_active: bool) -> None:
        """Update user status in the worksheet."""

        row_index = await self._sheets_client.find_row_index(
            USER_ID_COLUMN,
            str(user_id),
        )
        if not row_index:
            return

        status_value = "active" if is_active else "left"
        await self._sheets_client.update_cell(
            row_index,
            STATUS_COLUMN,
            status_value,
        )

    async def get_statistics(self) -> UserStatistics:
        """Return total/active/left stats from the worksheet."""

        rows = await self._sheets_client.fetch_raw_rows(skip_header=True)
        total = len(rows)
        active = 0
        left = 0

        for row in rows:
            status = ""
            if len(row) >= STATUS_COLUMN:
                status = row[STATUS_COLUMN - 1].strip().lower()
            if status == "left":
                left += 1
            else:
                active += 1

        return UserStatistics(total=total, active=active, left=left)

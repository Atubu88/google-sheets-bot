"""Service for working with Telegram users stored in Google Sheets."""
from __future__ import annotations

from datetime import datetime

from services.sheets_client import SheetsClient


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
        rows = await self._sheets_client.fetch_raw_rows(skip_header=True)

        for row in rows:
            if row and row[0] == user_id_str:
                return False

        await self._sheets_client.append_row(
            [
                user_id_str,
                str(chat_id),
                username or "",
                first_name or "",
                created_at.isoformat(),
            ]
        )
        return True

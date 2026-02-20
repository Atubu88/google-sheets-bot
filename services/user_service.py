"""Service for working with Telegram users stored in Google Sheets."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from services.sheets_client import SheetsClient


STATUS_COLUMN = 6
USER_ID_COLUMN = 1
CHAT_ID_COLUMN = 2


@dataclass(slots=True)
class UserStatistics:
    total: int
    active: int
    left: int


class UserService:
    """High-level operations for persisting and checking users."""

    def __init__(self, sheets_client: SheetsClient):
        self._sheets_client = sheets_client
        self._row_index_cache: dict[str, int] | None = None
        self._chat_row_index_cache: dict[str, int] | None = None
        self._status_cache: dict[str, str] | None = None
        self._last_row_index: int | None = None
        self._cache_lock = asyncio.Lock()
        self._user_locks: dict[str, asyncio.Lock] = {}
        self._user_locks_lock = asyncio.Lock()

    async def _get_user_lock(self, user_id: str) -> asyncio.Lock:
        async with self._user_locks_lock:
            lock = self._user_locks.get(user_id)
            if lock is None:
                lock = asyncio.Lock()
                self._user_locks[user_id] = lock
            return lock

    async def _ensure_row_index_cache(self) -> None:
        if self._row_index_cache is not None:
            return
        async with self._cache_lock:
            if self._row_index_cache is not None:
                return
            rows = await self._sheets_client.fetch_raw_rows(skip_header=False)
            cache: dict[str, int] = {}
            chat_cache: dict[str, int] = {}
            status_cache: dict[str, str] = {}
            for idx, row in enumerate(rows, start=1):
                if idx == 1:
                    continue
                if len(row) < USER_ID_COLUMN:
                    continue
                user_id = str(row[USER_ID_COLUMN - 1]).strip()
                if not user_id:
                    continue
                cache[user_id] = idx
                if len(row) >= CHAT_ID_COLUMN:
                    chat_id = str(row[CHAT_ID_COLUMN - 1]).strip()
                    if chat_id:
                        chat_cache[chat_id] = idx
                status_value = ""
                if len(row) >= STATUS_COLUMN:
                    status_value = str(row[STATUS_COLUMN - 1]).strip().lower()
                status_cache[user_id] = status_value or "active"
            self._row_index_cache = cache
            self._chat_row_index_cache = chat_cache
            self._status_cache = status_cache
            self._last_row_index = len(rows)

    async def _find_and_cache_row_index(self, user_id: int) -> int | None:
        row_index = await self._sheets_client.find_row_index(
            USER_ID_COLUMN,
            str(user_id),
        )
        if row_index:
            async with self._cache_lock:
                if self._row_index_cache is not None:
                    self._row_index_cache[str(user_id)] = row_index
                    if self._last_row_index is None or row_index > self._last_row_index:
                        self._last_row_index = row_index
                if self._status_cache is not None:
                    self._status_cache.setdefault(str(user_id), "active")
        return row_index

    async def _find_and_cache_row_index_by_chat_id(self, chat_id: int) -> int | None:
        row_index = await self._sheets_client.find_row_index(
            CHAT_ID_COLUMN,
            str(chat_id),
        )
        if row_index:
            async with self._cache_lock:
                if self._chat_row_index_cache is not None:
                    self._chat_row_index_cache[str(chat_id)] = row_index
                    if self._last_row_index is None or row_index > self._last_row_index:
                        self._last_row_index = row_index
        return row_index

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
        await self._ensure_row_index_cache()
        row_index = self._row_index_cache.get(user_id_str) if self._row_index_cache else None

        if row_index:
            user_lock = await self._get_user_lock(user_id_str)
            async with user_lock:
                cached_status = self._status_cache.get(user_id_str) if self._status_cache else None
                if cached_status == "active":
                    return False
                await self._sheets_client.update_cell(row_index, STATUS_COLUMN, "active")
                async with self._cache_lock:
                    if self._status_cache is not None:
                        self._status_cache[user_id_str] = "active"
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
        async with self._cache_lock:
            if self._row_index_cache is not None:
                next_row_index = (self._last_row_index or 0) + 1
                self._row_index_cache[user_id_str] = next_row_index
                if self._chat_row_index_cache is not None:
                    self._chat_row_index_cache[str(chat_id)] = next_row_index
                self._last_row_index = next_row_index
            if self._status_cache is not None:
                self._status_cache[user_id_str] = "active"
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
        await self._ensure_row_index_cache()
        user_id_str = str(user_id)
        user_lock = await self._get_user_lock(user_id_str)
        async with user_lock:
            row_index = self._row_index_cache.get(user_id_str) if self._row_index_cache else None
            if not row_index:
                row_index = await self._find_and_cache_row_index(user_id)
            if not row_index:
                return

            status_value = "active" if is_active else "left"
            cached_status = self._status_cache.get(user_id_str) if self._status_cache else None
            if cached_status == status_value:
                return
            await self._sheets_client.update_cell(
                row_index,
                STATUS_COLUMN,
                status_value,
            )
            async with self._cache_lock:
                if self._status_cache is not None:
                    self._status_cache[user_id_str] = status_value

    async def update_status_by_chat_id(self, chat_id: int, is_active: bool) -> None:
        """Update user status in the worksheet by chat_id column."""
        await self._ensure_row_index_cache()
        chat_id_str = str(chat_id)
        row_index = self._chat_row_index_cache.get(chat_id_str) if self._chat_row_index_cache else None
        if not row_index:
            row_index = await self._find_and_cache_row_index_by_chat_id(chat_id)
        if not row_index:
            return

        status_value = "active" if is_active else "left"
        cached_user_id: str | None = None
        cached_status: str | None = None
        if self._row_index_cache is not None and self._status_cache is not None:
            for current_user_id, current_row_index in self._row_index_cache.items():
                if current_row_index == row_index:
                    cached_user_id = current_user_id
                    cached_status = self._status_cache.get(current_user_id)
                    break

        if cached_status == status_value:
            return

        await self._sheets_client.update_cell(
            row_index,
            STATUS_COLUMN,
            status_value,
        )
        async with self._cache_lock:
            if self._status_cache is not None and cached_user_id is not None:
                self._status_cache[cached_user_id] = status_value

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

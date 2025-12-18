"""Google Sheets client layer.

This module isolates all direct communication with Google Sheets using
`gspread`. It exposes a small async API to fetch rows for higher layers.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

import gspread
from google.oauth2.service_account import Credentials


@dataclass
class SheetRow:
    """Typed representation of a row returned from Google Sheets."""

    id: str
    name: str
    short_desc: str
    description: str
    photo_url: str
    old_price: Optional[str]
    price: str
    is_promo: bool

    @classmethod
    def from_sequence(cls, values: Sequence[str]) -> "SheetRow":
        # Ensure we always have exactly eight fields.
        padded = list(values) + [""] * (8 - len(values))
        old_price = padded[5].strip() or None
        is_promo = str(padded[7]).upper() == "TRUE"
        return cls(
            id=padded[0],
            name=padded[1],
            short_desc=padded[2],
            description=padded[3],
            photo_url=padded[4],
            old_price=old_price,
            price=padded[6],
            is_promo=is_promo,
        )


class SheetsClient:
    """A minimal wrapper around gspread for reading data asynchronously."""

    def __init__(
        self,
        service_account_file: Path,
        spreadsheet_id: str,
        worksheet_name: str,
    ):
        self._service_account_file = service_account_file
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_name = worksheet_name
        self._client: gspread.Client | None = None

    def _build_client(self) -> gspread.Client:
        # Универсальные scopes: чтение + запись + стабильная работа с Drive
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        credentials = Credentials.from_service_account_file(
            str(self._service_account_file),
            scopes=scopes,
        )
        return gspread.authorize(credentials)

    async def _get_worksheet(self) -> gspread.Worksheet:
        if self._client is None:
            self._client = await asyncio.to_thread(self._build_client)

        # Используем open_by_url — самый устойчивый вариант между аккаунтами
        spreadsheet = await asyncio.to_thread(
            self._client.open_by_url,
            f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}",
        )
        return await asyncio.to_thread(
            spreadsheet.worksheet,
            self._worksheet_name,
        )

    async def fetch_raw_rows(self, *, skip_header: bool = True) -> list[list[str]]:
        """Fetch raw rows from the worksheet.

        Args:
            skip_header: Whether to exclude the first header row from the
                returned dataset.
        """
        worksheet = await self._get_worksheet()
        raw_rows: list[list[str]] = await asyncio.to_thread(
            worksheet.get_all_values
        )

        if not raw_rows:
            return []

        if skip_header:
            return raw_rows[1:]
        return raw_rows

    async def append_row(self, values: Sequence[str]) -> None:
        """Append a row to the worksheet."""
        worksheet = await self._get_worksheet()
        await asyncio.to_thread(
            worksheet.append_row,
            list(values),
        )

    async def update_cell(self, row: int, col: int, value: str) -> None:
        """Update a specific cell in the worksheet."""
        worksheet = await self._get_worksheet()
        await asyncio.to_thread(
            worksheet.update_cell,
            row,
            col,
            value,
        )

    async def fetch_rows(self) -> List[SheetRow]:
        """Fetch all rows (excluding header) from the worksheet."""
        data_rows = await self.fetch_raw_rows(skip_header=True)
        return [
            row
            for row in (SheetRow.from_sequence(row) for row in data_rows)
            if row.is_promo
        ]

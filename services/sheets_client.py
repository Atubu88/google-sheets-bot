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
import os
import json


@dataclass
class SheetRow:
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
        padded = list(values) + [""] * (8 - len(values))
        return cls(
            id=padded[0],
            name=padded[1],
            short_desc=padded[2],
            description=padded[3],
            photo_url=padded[4],
            old_price=padded[5].strip() or None,
            price=padded[6],
            is_promo=str(padded[7]).upper() == "TRUE",
        )


class SheetsClient:
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
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        if "GOOGLE_SERVICE_ACCOUNT_JSON" in os.environ:
            credentials = Credentials.from_service_account_info(
                json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
                scopes=scopes,
            )
        else:
            credentials = Credentials.from_service_account_file(
                str(self._service_account_file),
                scopes=scopes,
            )

        return gspread.authorize(credentials)

    async def _get_worksheet(self) -> gspread.Worksheet:
        if self._client is None:
            self._client = await asyncio.to_thread(self._build_client)

        spreadsheet = await asyncio.to_thread(
            self._client.open_by_url,
            f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}",
        )

        return await asyncio.to_thread(
            spreadsheet.worksheet,
            self._worksheet_name,
        )

    async def fetch_raw_rows(self, *, skip_header: bool = True) -> list[list[str]]:
        worksheet = await self._get_worksheet()
        rows: list[list[str]] = await asyncio.to_thread(
            worksheet.get_all_values
        )

        if skip_header and rows:
            return rows[1:]

        return rows

    async def fetch_rows(self) -> List[SheetRow]:
        raw_rows = await self.fetch_raw_rows(skip_header=True)
        return [SheetRow.from_sequence(row) for row in raw_rows]

    async def append_row(self, values: Sequence[str]) -> None:
        worksheet = await self._get_worksheet()
        await asyncio.to_thread(worksheet.append_row, list(values))

    async def update_cell(self, row: int, col: int, value: str) -> None:
        worksheet = await self._get_worksheet()
        await asyncio.to_thread(worksheet.update_cell, row, col, value)

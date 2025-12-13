"""Simple helper to read promo products from Google Sheets."""
from __future__ import annotations

from typing import Dict, List

import gspread
from google.oauth2.service_account import Credentials

from config import get_settings


def get_promo_products() -> List[Dict[str, str]]:
    """Return products marked as promo on the ``Products`` sheet.

    The function uses the Google Sheets API with service-account credentials to
    read rows from the ``Products`` worksheet. Only rows where ``is_promo`` is
    TRUE are returned.
    """

    settings = get_settings()

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    credentials = Credentials.from_service_account_file(
        str(settings.service_account_file), scopes=scopes
    )
    client = gspread.authorize(credentials)

    worksheet = client.open_by_key(settings.spreadsheet_id).worksheet("Products")
    rows = worksheet.get_all_records()

    promo_products: List[Dict[str, str]] = []
    for row in rows:
        if str(row.get("is_promo", "")).upper() != "TRUE":
            continue

        promo_products.append(
            {
                "id": str(row.get("id", "")),
                "name": str(row.get("name", "")),
                "description": str(row.get("description", "")),
                "photo_url": str(row.get("photo_url", "")),
                "price": str(row.get("price", "")),
                "is_promo": True,
            }
        )

    return promo_products

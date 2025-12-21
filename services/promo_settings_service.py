"""Helpers for reading promo settings from Google Sheets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from services.sheets_client import SheetsClient


@dataclass(slots=True)
class PromoSettings:
    enabled: bool
    interval_days: int
    send_time: time
    last_sent_date: Optional[date]


class PromoSettingsService:
    """Read and update promo settings stored in Google Sheets."""

    _kyiv_tz = ZoneInfo("Europe/Kyiv")

    def __init__(self, sheets_client: SheetsClient):
        self._sheets_client = sheets_client

    async def get_settings(self) -> PromoSettings:
        rows = await self._sheets_client.fetch_raw_rows(skip_header=True)
        row = rows[0] if rows else []

        enabled = str(row[0]).upper() == "TRUE" if len(row) > 0 else False
        interval_days = int(row[1]) if len(row) > 1 and str(row[1]).isdigit() else 0
        send_time_str = row[2] if len(row) > 2 else "00:00"
        send_time = self._parse_send_time(send_time_str)
        last_sent_date = self._parse_last_sent_date(row[3] if len(row) > 3 else "")

        return PromoSettings(
            enabled=enabled,
            interval_days=interval_days,
            send_time=send_time,
            last_sent_date=last_sent_date,
        )

    async def update_last_sent_date(self, value: date) -> None:
        # Header row is 1, data row is 2, last_sent_date column is 4
        await self._sheets_client.update_cell(
            2,
            4,
            value.isoformat(),
        )

    def _parse_send_time(self, value: str) -> time:
        try:
            hours, minutes = value.split(":", maxsplit=1)
            return time(int(hours), int(minutes))
        except Exception:
            return time(0, 0)

    def _parse_last_sent_date(self, value: str) -> Optional[date]:
        if not value:
            return None

        try:
            parsed_date = date.fromisoformat(value)
        except Exception:
            parsed_date = None

        if parsed_date is not None:
            return parsed_date

        try:
            parsed_datetime = datetime.fromisoformat(value)
        except Exception:
            return None

        if parsed_datetime.tzinfo is None:
            parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
        return parsed_datetime.astimezone(self._kyiv_tz).date()

    def should_send_now(self, settings: PromoSettings, now: datetime) -> bool:
        now = now.astimezone(self._kyiv_tz)
        if not settings.enabled:
            return False

        today = now.date()
        today_send_time = datetime.combine(
            today,
            settings.send_time,
            tzinfo=self._kyiv_tz,
        )
        if now < today_send_time:
            return False

        if settings.last_sent_date is None:
            return True

        if settings.last_sent_date == today:
            return False

        next_allowed = settings.last_sent_date + timedelta(days=settings.interval_days)
        if today < next_allowed:
            return False

        return True

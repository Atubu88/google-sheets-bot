"""Helpers for reading promo settings from Google Sheets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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

    # ⏰ ЯВНО фиксируем таймзону Украины
    _kyiv_tz = ZoneInfo("Europe/Kyiv")

    def __init__(self, sheets_client: SheetsClient):
        self._sheets_client = sheets_client

    async def get_settings(self) -> PromoSettings:
        rows = await self._sheets_client.fetch_raw_rows(skip_header=True)
        row = rows[0] if rows else []

        enabled = str(row[0]).upper() == "TRUE" if len(row) > 0 else False

        # 🔧 FIX: если интервал 0 или мусор — считаем как 1 день
        # Это предотвращает повторную отправку в тот же день
        interval_days = int(row[1]) if len(row) > 1 and str(row[1]).isdigit() else 0
        interval_days = max(1, interval_days)

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
        # ✅ Записываем ТОЛЬКО дату в формате YYYY-MM-DD
        # Никаких datetime и timezone — это критично для стабильности
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
            # 🛡 Защита от кривых данных в Google Sheets
            return time(0, 0)

    def _parse_last_sent_date(self, value: str) -> Optional[date]:
        # 🔧 FIX (КЛЮЧЕВОЙ):
        # Google Sheets может вернуть datetime, строку с временем или мусор.
        # Мы ЖЁСТКО берём ТОЛЬКО YYYY-MM-DD и игнорируем всё остальное.
        if not value:
            return None

        try:
            return date.fromisoformat(str(value)[:10])
        except Exception:
            return None

    def should_send_now(self, settings: PromoSettings, now: datetime) -> bool:
        # ⏰ ВСЕ вычисления делаем строго по времени Украины
        now = now.astimezone(self._kyiv_tz)
        today = now.date()

        if not settings.enabled:
            return False

        # 🔒 FIX:
        # Если сегодня (по Украине) уже отправляли — НИКОГДА не шлём снова
        if settings.last_sent_date == today:
            return False

        # ⏱ Проверяем, наступило ли время отправки сегодня
        today_send_time = datetime.combine(
            today,
            settings.send_time,
            tzinfo=self._kyiv_tz,
        )
        if now < today_send_time:
            return False

        # 🆕 Если ещё ни разу не отправляли — можно отправлять
        if settings.last_sent_date is None:
            return True

        # 📆 FIX:
        # Интервал считается ТОЛЬКО по датам, без часов и минут
        next_allowed_date = settings.last_sent_date + timedelta(
            days=settings.interval_days
        )

        return today >= next_allowed_date

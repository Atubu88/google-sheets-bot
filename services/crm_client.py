"""Client for sending orders to LP-CRM via HTTP API."""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp


class LPCRMClient:
    """Lightweight HTTP client for LP-CRM order creation."""

    def __init__(self, *, api_key: str, base_url: str, office_id: int) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._office_id = office_id
        self._logger = logging.getLogger(self.__class__.__name__)

    async def send_order(
        self,
        *,
        order_id: str,
        country: str,
        site: str,
        buyer_name: str,
        phone: str,
        comment: str,
        product_id: str,
        price: str,
    ) -> None:
        """Create an order in LP-CRM."""

        payload = {
            "key": self._api_key,
            "order_id": order_id,
            "country": country,
            "site": site,
            "bayer_name": buyer_name,
            "phone": phone,
            "comment": comment,
            "office": self._office_id,
            "products": self._serialize_products(product_id, price),
        }

        url = f"{self._base_url}/api/addNewOrder.html"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload) as response:
                response_text = await response.text()
                if response.status != 200:
                    raise RuntimeError(
                        f"LP-CRM returned status {response.status}: {response_text}"
                    )

                await self._log_response(response_text)

    async def _log_response(self, response_text: str) -> None:
        """Attempt to parse and log CRM response for observability."""

        try:
            parsed: Any = json.loads(response_text)
        except Exception:
            parsed = None

        if isinstance(parsed, dict):
            status = str(parsed.get("status") or parsed.get("success") or "").lower()
            if status not in {"ok", "true", "1"}:
                self._logger.warning("LP-CRM responded with potential error: %s", parsed)
            else:
                self._logger.info("LP-CRM order created: %s", parsed)
        else:
            self._logger.info("LP-CRM raw response: %s", response_text)

    def _serialize_products(self, product_id: str, price: str) -> str:
        product_id_int = self._safe_int(product_id)
        price_int = self._safe_int(price)

        return (
            "a:1:{i:0;a:3:{s:10:\"product_id\";i:"  # prefix
            f"{product_id_int};s:5:\"price\";i:{price_int};s:5:\"count\";i:1;}}"
        )

    def _safe_int(self, value: str) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            digits = "".join(ch for ch in str(value) if ch.isdigit())
            if digits:
                return int(digits)
            raise ValueError(f"Cannot convert {value!r} to integer for LP-CRM payload")

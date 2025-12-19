"""Client for sending orders to LP-CRM via HTTP API."""
from __future__ import annotations

import json
import logging
from typing import Any
import urllib.parse

import aiohttp
import phpserialize


class LPCRMClient:
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
        products = self._serialize_products(product_id, price)

        payload = {
            "key": self._api_key,
            "order_id": order_id,
            "country": country,
            "site": site,
            "office": self._office_id,
            "bayer_name": buyer_name,
            "phone": phone,
            "comment": comment,
            "products": products,
        }

        self._logger.info(
            "Sending order to LP-CRM | order_id=%s | product_id=%s | price=%s | office=%s",
            order_id, product_id, price, self._office_id
        )

        url = f"{self._base_url}/api/addNewOrder.html"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload) as response:
                response_text = await response.text()

                if response.status != 200:
                    raise RuntimeError(
                        f"LP-CRM returned status {response.status}: {response_text}"
                    )

                self._log_response(response_text)

    def _log_response(self, response_text: str) -> None:
        try:
            parsed: Any = json.loads(response_text)
        except Exception:
            parsed = None

        if isinstance(parsed, dict):
            status = str(parsed.get("status")).lower()
            if status == "ok":
                self._logger.info("LP-CRM order created successfully: %s", parsed)
            else:
                self._logger.warning("LP-CRM error response: %s", parsed)
        else:
            self._logger.info("LP-CRM raw response: %s", response_text)

    def _serialize_products(self, product_id: str, price: str) -> str:
        products = {
            0: {
                "product_id": int(product_id),
                "price": int(price),
                "count": 1,
            }
        }
        serialized = phpserialize.dumps(products)
        return urllib.parse.quote(serialized)

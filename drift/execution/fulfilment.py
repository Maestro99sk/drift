"""Auto-fulfilment via CJ. Triggered by sale webhook in monitoring layer."""

from __future__ import annotations

import logging

import httpx

from drift.config import get_settings
from drift.execution.base import FulfilmentAdapter, FulfilmentResult

log = logging.getLogger(__name__)


class CJFulfilmentAdapter(FulfilmentAdapter):
    CREATE_ORDER_URL = "https://developers.cjdropshipping.com/api2.0/v1/shopping/order/createOrder"

    def __init__(self) -> None:
        self.api_key = get_settings().cj_api_key
        self._token: str | None = None

    async def _ensure_token(self, client: httpx.AsyncClient) -> str | None:
        if self._token:
            return self._token
        from drift.sourcing.cj import AUTH_URL

        resp = await client.post(AUTH_URL, json={"email": "", "apiKey": self.api_key})
        if resp.status_code != 200:
            return None
        self._token = (resp.json().get("data") or {}).get("accessToken")
        return self._token

    async def submit(self, *, supplier_sku: str, quantity: int, ship_to: dict) -> FulfilmentResult:
        if not self.api_key:
            raise RuntimeError("CJ credentials missing - fulfilment dormant")

        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._ensure_token(client)
            if not token:
                return FulfilmentResult(supplier_order_id="", status="failed")
            headers = {"CJ-Access-Token": token}
            payload = {
                "products": [{"vid": supplier_sku, "quantity": quantity}],
                "shippingZip": ship_to.get("zip"),
                "shippingCountryCode": ship_to.get("country"),
                "shippingProvince": ship_to.get("province"),
                "shippingCity": ship_to.get("city"),
                "shippingAddress": ship_to.get("address"),
                "shippingCustomerName": ship_to.get("name"),
                "shippingPhone": ship_to.get("phone"),
            }
            resp = await client.post(self.CREATE_ORDER_URL, headers=headers, json=payload)
            if resp.status_code != 200:
                log.warning("CJ order failed: %s", resp.text)
                return FulfilmentResult(supplier_order_id="", status="failed")
            data = resp.json().get("data") or {}
            return FulfilmentResult(
                supplier_order_id=str(data.get("orderId", "")), status="submitted"
            )


class MockFulfilmentAdapter(FulfilmentAdapter):
    async def submit(self, *, supplier_sku, quantity, ship_to):
        return FulfilmentResult(
            supplier_order_id=f"mock-order-{abs(hash(supplier_sku)) % 10**8}",
            status="submitted",
        )

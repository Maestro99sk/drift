"""CJ Dropshipping adapter - live.

CJ's public API requires a bearer token obtained via an auth call. Keep the auth flow
small and stateful: cache the token per process; refresh on 401.
"""

from __future__ import annotations

import logging
import time

import httpx

from drift.config import get_settings
from drift.sourcing.base import SourcingAdapter, SourcingResult

log = logging.getLogger(__name__)

AUTH_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken"
SEARCH_URL = "https://developers.cjdropshipping.com/api2.0/v1/product/list"


class CJSourcingAdapter(SourcingAdapter):
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_settings().cj_api_key
        self._token: str | None = None
        self._token_expiry: float = 0.0

    async def _get_token(self, client: httpx.AsyncClient) -> str | None:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        if not self.api_key:
            return None
        resp = await client.post(AUTH_URL, json={"email": "", "apiKey": self.api_key})
        if resp.status_code != 200:
            log.warning("CJ auth failed: %s", resp.text)
            return None
        data = resp.json().get("data") or {}
        token = data.get("accessToken")
        if not token:
            return None
        self._token = token
        # CJ tokens typically last ~14 days; play safe and refresh after 12h.
        self._token_expiry = time.time() + 12 * 3600
        return token

    async def find(self, keyword: str, category: str) -> SourcingResult | None:
        if not self.api_key:
            log.info("CJ API key missing - sourcing dormant")
            return None
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._get_token(client)
            if not token:
                return None
            headers = {"CJ-Access-Token": token}
            params = {"productNameEn": keyword, "pageNum": 1, "pageSize": 1}
            try:
                resp = await client.get(SEARCH_URL, headers=headers, params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("CJ search failed for %r: %s", keyword, exc)
                return None
            items = (resp.json().get("data") or {}).get("list") or []
            if not items:
                return None
            it = items[0]
            unit_cost = float(it.get("sellPrice") or 0.0)
            ship_days = int(it.get("shippingTime", 12))
            # CJ exposes "score" and seller reliability hints; combine pragmatically.
            reliability = min(1.0, float(it.get("listedNum", 0)) / 10000) * 0.5 + 0.5
            suggested = unit_cost * 3.0  # standard dropshipping 3x cost markup
            return SourcingResult(
                supplier="cj",
                supplier_sku=str(it.get("pid")),
                unit_cost=unit_cost,
                ship_days=ship_days,
                reliability_score=reliability,
                stock=int(it.get("inventory", 0) or 0),
                suggested_sell_price=suggested,
                saturation=min(1.0, float(it.get("listedNum", 0)) / 20000),
            )

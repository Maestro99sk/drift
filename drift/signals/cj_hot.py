"""CJ Dropshipping 'hot products' signal adapter.

Inverts the original Drift discovery model: instead of finding a trend on social
and then trying to source it, we read what's actually selling on a real
dropshipping supplier's catalog. Every signal arrives already-sourced - SKU,
unit cost, ship time, stock and saturation are all in the raw payload, so the
orchestrator can skip the keyword->supplier matching step entirely.

Why this is the better default for a live dropshipping store:
  * No 'unsourceable winner' gap - if it's on CJ, you can ship it tomorrow.
  * Margin and reliability data flow in with the signal, not separately.
  * Saturation is the count of other CJ merchants already listing the same SKU
    (`listedNum`) - a real competitive-density number, not a guess from search
    trend curves.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from drift.config import get_settings
from drift.signals.base import RawSignal, SignalAdapter
from drift.signals.google_trends import _classify_category

log = logging.getLogger(__name__)

AUTH_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken"
LIST_URL = "https://developers.cjdropshipping.com/api2.0/v1/product/list"


class CJHotProductsAdapter(SignalAdapter):
    """Pull popular CJ products as RawSignals, pre-loaded with sourcing data.

    Note: CJ caps page_size at 200 and rate-limits aggressively. We grab a
    single page of top sellers per call; the loop runs again on the next tick.
    """

    def __init__(self, api_key: str | None = None, page_size: int = 50) -> None:
        self.api_key = api_key or get_settings().cj_api_key
        self.page_size = min(page_size, 200)
        self._token: str | None = None
        self._token_expiry: float = 0.0

    async def fetch(self, *, limit: int = 50) -> list[RawSignal]:
        if not self.api_key:
            log.info("CJ_API_KEY missing - CJHotProductsAdapter returning empty list")
            return []

        # Bias the search toward the focus niche when one is set.
        s = get_settings()
        focus = s.focus_list()
        # CJ search uses productNameEn; widening these aliases catches more inventory.
        search_terms = {
            "kids": "kids toys",
            "fashion": "women dress",
            "beauty": "skincare",
            "home": "kitchen gadget",
            "fitness": "fitness band",
            "pets": "pet supplies",
            "gadgets": "wireless gadget",
        }
        keyword = search_terms.get(focus[0], "") if len(focus) == 1 else ""

        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._get_token(client)
            if not token:
                return []

            params: dict[str, Any] = {
                "pageNum": 1,
                "pageSize": self.page_size,
                # CJ's `sort` accepts e.g. "listedNum,desc" - more listings = more
                # external interest. Without an explicit sales endpoint this is
                # our best proxy for 'hot'.
                "sort": "listedNum,desc",
            }
            if keyword:
                params["productNameEn"] = keyword

            try:
                resp = await client.get(LIST_URL, headers={"CJ-Access-Token": token}, params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("CJ hot products fetch failed: %s", exc)
                return []
            items = (resp.json().get("data") or {}).get("list") or []

        signals: list[RawSignal] = []
        for item in items[:limit]:
            sig = _item_to_signal(item)
            if sig is None:
                continue
            # Respect focus mode even when the search query is broad.
            if focus and not s.is_focused(sig.category):
                continue
            signals.append(sig)
        return signals

    async def _get_token(self, client: httpx.AsyncClient) -> str | None:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        resp = await client.post(AUTH_URL, json={"email": "", "apiKey": self.api_key})
        if resp.status_code != 200:
            log.warning("CJ auth failed: %s", resp.text)
            return None
        token = ((resp.json().get("data") or {}).get("accessToken")) or None
        if not token:
            return None
        self._token = token
        self._token_expiry = time.time() + 12 * 3600
        return token


def _item_to_signal(item: dict) -> RawSignal | None:
    """Translate a CJ catalog row into a RawSignal with pre-sourced fields baked in."""
    name = (item.get("productNameEn") or item.get("productName") or "").strip()
    sku = item.get("pid")
    if not name or not sku:
        return None
    unit_cost = float(item.get("sellPrice") or 0.0)
    if unit_cost <= 0:
        return None

    listed = float(item.get("listedNum", 0) or 0)
    inventory = int(item.get("inventory", 0) or 0)
    ship_days = int(item.get("shippingTime", 12) or 12)

    # CJ doesn't expose a velocity directly. Use a neutral-positive default for
    # bestsellers (they made the top of listedNum sort, so they're at least warm).
    velocity = 0.6
    # Saturation = how crowded the SKU already is among CJ sellers, normalised.
    saturation = min(1.0, listed / 20000.0)
    # Reliability is a CJ-internal hint mixing the listing's age, reviews and
    # fulfilment record. Fall back to a conservative 0.75 baseline if absent.
    reliability = max(0.5, min(1.0, float(item.get("score") or 0.75)))

    # Suggested sell price: standard 3x dropshipping markup, rounded.
    suggested_sell_price = round(unit_cost * 3.0, 2)

    return RawSignal(
        source="cj_hot",
        keyword=name,
        category=_classify_category(name),
        trend_velocity=velocity,
        saturation=saturation,
        raw={
            "pid": sku,
            # The pre-sourced bundle: orchestrator can build a SourcingResult
            # without going back to CJ for a second search.
            "pre_sourced": {
                "supplier": "cj",
                "supplier_sku": str(sku),
                "unit_cost": unit_cost,
                "ship_days": ship_days,
                "reliability_score": reliability,
                "stock": inventory,
                "suggested_sell_price": suggested_sell_price,
                "saturation": saturation,
            },
            "listed_num": listed,
        },
    )


# Compatibility shim: make this adapter cleanly mockable in tests.
async def _noop_sleep() -> None:
    await asyncio.sleep(0)

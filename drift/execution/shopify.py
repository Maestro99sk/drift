"""Shopify storefront adapter - live via Admin API.

A single Shopify store backs multiple niche-styled storefronts. Niche skinning is done at
the LANDING-page level (different theme/section) keyed by UTM - see `niche_theme` and
`utm_key`. The Shopify product itself is one entity per SKU.
"""

from __future__ import annotations

import logging

import httpx

from drift.config import get_settings
from drift.execution.base import PublishResult, StorefrontAdapter

log = logging.getLogger(__name__)

API_VERSION = "2024-10"


class ShopifyStorefrontAdapter(StorefrontAdapter):
    def __init__(self, token: str | None = None, domain: str | None = None) -> None:
        s = get_settings()
        self.token = token or s.shopify_admin_token
        self.domain = domain or s.shopify_store_domain

    @property
    def _base_url(self) -> str:
        return f"https://{self.domain}/admin/api/{API_VERSION}"

    async def publish(
        self,
        *,
        title: str,
        body_html: str,
        price: float,
        sku: str,
        niche_theme: str,
        utm_key: str,
    ) -> PublishResult:
        if not (self.token and self.domain):
            raise RuntimeError("Shopify credentials missing - storefront dormant")

        payload = {
            "product": {
                "title": title,
                "body_html": body_html,
                # COMPLIANCE TODO: ship-time disclosure, returns policy must be linked
                # in body_html for EU/UK markets per consumer-rights rules.
                "vendor": "Drift",
                "product_type": niche_theme,
                "tags": [niche_theme, f"utm:{utm_key}"],
                "variants": [{"price": f"{price:.2f}", "sku": sku, "inventory_management": None}],
                "status": "active",
            }
        }
        headers = {
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{self._base_url}/products.json", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()["product"]

        handle = data["handle"]
        return PublishResult(
            external_id=str(data["id"]),
            storefront_url=f"https://{self.domain}/products/{handle}?utm={utm_key}",
        )


class MockStorefrontAdapter(StorefrontAdapter):
    async def publish(
        self,
        *,
        title: str,
        body_html: str,
        price: float,
        sku: str,
        niche_theme: str,
        utm_key: str,
    ) -> PublishResult:
        fake_id = f"mock-{abs(hash(sku)) % 10**8}"
        return PublishResult(
            external_id=fake_id,
            storefront_url=f"https://mock.drift.local/{niche_theme}/{fake_id}?utm={utm_key}",
        )

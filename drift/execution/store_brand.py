"""Sync store-level brand identity (title, tagline, brand colors) to Shopify.

Driven by what's actually live in the store: pick the niche with the most
active products and skin the storefront for it. Re-runnable - call after
every approval and the brand drifts with the loop.

Best-effort: each Shopify mutation is wrapped so missing scopes log a
warning rather than break the publish flow. The publish itself remains
the source of truth for 'success'.
"""

from __future__ import annotations

import logging
from collections import Counter

import httpx

from drift.config import get_settings
from drift.execution.shopify import API_VERSION, ShopifyError

log = logging.getLogger(__name__)


# Per-niche colour palettes. Hand-picked because brand visuals matter more than
# anything an LLM would auto-pick; widening the palette is a one-line change.
NICHE_PALETTE: dict[str, tuple[str, str]] = {
    "kids": ("#F8C8DC", "#3C3C8A"),
    "fashion": ("#1a1a1a", "#d4af37"),
    "beauty": ("#FBE7EA", "#9B2C5D"),
    "home": ("#EDE6DA", "#3C4A3E"),
    "fitness": ("#0F1417", "#FF6B35"),
    "pets": ("#FFF6E0", "#A55833"),
    "gadgets": ("#0B0F19", "#00D4FF"),
    "general": ("#FAFAFA", "#1D1D1F"),
}

NICHE_TAGLINE: dict[str, str] = {
    "kids": "Learning gear that holds up to actual kids.",
    "fashion": "Wear-it-this-week pieces, not seasonal hype.",
    "beauty": "Routines worth the counter space.",
    "home": "Quiet upgrades for the rooms you live in.",
    "fitness": "Built for the workouts you actually finish.",
    "pets": "Stuff your pet will tolerate. Maybe even love.",
    "gadgets": "Useful tech with a real job to do.",
    "general": "Trending picks, curated weekly.",
}


def _palette(niche: str) -> tuple[str, str]:
    return NICHE_PALETTE.get(niche, NICHE_PALETTE["general"])


def _tagline(niche: str) -> str:
    return NICHE_TAGLINE.get(niche, NICHE_TAGLINE["general"])


def _store_title(niche: str) -> str:
    pretty = niche.replace("-", " ").replace("_", " ").title()
    if niche == "general":
        return "Drift"
    return f"Drift - {pretty}"


async def _gql(client: httpx.AsyncClient, query: str, variables: dict) -> dict:
    s = get_settings()
    url = f"https://{s.shopify_store_domain}/admin/api/{API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": s.shopify_admin_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = await client.post(url, headers=headers, json={"query": query, "variables": variables})
    if resp.status_code >= 400:
        raise ShopifyError(f"Shopify HTTP {resp.status_code}: {resp.text}")
    payload = resp.json()
    if payload.get("errors"):
        raise ShopifyError(f"Shopify GraphQL errors: {payload['errors']}")
    return payload["data"]


async def _dominant_niche(client: httpx.AsyncClient) -> str:
    """Pick the niche that owns the most active products. Falls back to 'general'."""
    query = """
    {
        products(first: 100, query: "status:active") {
            edges { node { productType } }
        }
    }
    """
    try:
        data = await _gql(client, query, {})
    except ShopifyError as exc:
        log.warning("dominant_niche query failed: %s", exc)
        return "general"
    counts: Counter[str] = Counter()
    for edge in data["products"]["edges"]:
        ptype = (edge["node"].get("productType") or "").strip().lower()
        if ptype:
            counts[ptype] += 1
    if not counts:
        return "general"
    return counts.most_common(1)[0][0]


async def _apply_shop_brand(client: httpx.AsyncClient, niche: str) -> None:
    """Update shop name + brand colors to fit the dominant niche."""
    primary, accent = _palette(niche)
    title = _store_title(niche)
    tagline = _tagline(niche)

    # 1. Shop name / contact email / etc. via shopUpdate.
    shop_query = """
    mutation driftShopUpdate($input: ShopInput!) {
        shopUpdate(input: $input) {
            userErrors { field message }
        }
    }
    """
    try:
        data = await _gql(client, shop_query, {"input": {"name": title}})
        ue = data["shopUpdate"]["userErrors"]
        if ue:
            log.warning("shopUpdate userErrors: %s", ue)
        else:
            log.info("Shop renamed to %r for niche %r", title, niche)
    except ShopifyError as exc:
        log.warning("shopUpdate skipped (%s)", exc)

    # 2. Brand colors via the Brand API. Requires write_brand scope.
    brand_query = """
    mutation driftBrandUpdate($input: BrandInput!) {
        brandUpdate(input: $input) {
            userErrors { field message }
        }
    }
    """
    brand_input = {
        "input": {
            "shortDescription": tagline,
            "slogan": tagline,
            "colors": {
                "primary": [{"background": primary, "foreground": accent}],
                "secondary": [{"background": accent, "foreground": primary}],
            },
        }
    }
    try:
        data = await _gql(client, brand_query, brand_input)
        ue = data["brandUpdate"]["userErrors"]
        if ue:
            log.warning("brandUpdate userErrors: %s", ue)
        else:
            log.info("Brand re-skinned for %r: primary=%s accent=%s", niche, primary, accent)
    except ShopifyError as exc:
        log.warning("brandUpdate skipped (%s). Add write_brand scope to enable.", exc)


async def sync_store_brand() -> None:
    """Re-skin the storefront based on the dominant niche. Safe to call after each publish."""
    s = get_settings()
    if not (s.shopify_admin_token and s.shopify_store_domain):
        return
    async with httpx.AsyncClient(timeout=30) as client:
        niche = await _dominant_niche(client)
        log.info("Re-skinning storefront for dominant niche: %s", niche)
        await _apply_shop_brand(client, niche)

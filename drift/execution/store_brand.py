"""Sync storefront brand identity to whatever niche currently dominates the catalog.

Shopify's Admin GraphQL has no `shopUpdate` / `brandUpdate` mutations (the store
name + brand-asset settings live in the admin UI, not the API). What we CAN
update programmatically is the active theme's `config/settings_data.json` -
that's where color tokens, hero gradients, etc. live for Dawn-family themes.

So the flow is:
  1. Look at every active product, pick the dominant `productType` (= niche).
  2. Fetch the active (main) theme.
  3. Fetch its config/settings_data.json (Theme Asset REST endpoint).
  4. Patch color settings for that niche, JSON.dumps, PUT back.

Best-effort: if write_themes / read_themes scopes are missing, or if the
theme doesn't use Dawn-style color tokens, we log a warning and skip.
"""

from __future__ import annotations

import json
import logging
from collections import Counter

import httpx

from drift.config import get_settings
from drift.execution.shopify import API_VERSION, ShopifyError

log = logging.getLogger(__name__)


# Per-niche colour palettes (background, accent). Hand-picked - visual identity
# matters more than anything an LLM would auto-generate. Extend freely.
NICHE_PALETTE: dict[str, tuple[str, str]] = {
    "kids": ("#FFF8FA", "#3C3C8A"),
    "fashion": ("#1A1A1A", "#D4AF37"),
    "beauty": ("#FBE7EA", "#9B2C5D"),
    "home": ("#EDE6DA", "#3C4A3E"),
    "fitness": ("#0F1417", "#FF6B35"),
    "pets": ("#FFF6E0", "#A55833"),
    "gadgets": ("#0B0F19", "#00D4FF"),
    "other": ("#FAFAFA", "#1D1D1F"),
}


def _palette(niche: str) -> tuple[str, str]:
    return NICHE_PALETTE.get(niche.lower(), NICHE_PALETTE["other"])


def _headers() -> dict[str, str]:
    s = get_settings()
    return {
        "X-Shopify-Access-Token": s.shopify_admin_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _gql(client: httpx.AsyncClient, query: str, variables: dict) -> dict:
    s = get_settings()
    url = f"https://{s.shopify_store_domain}/admin/api/{API_VERSION}/graphql.json"
    resp = await client.post(url, headers=_headers(), json={"query": query, "variables": variables})
    if resp.status_code >= 400:
        raise ShopifyError(f"Shopify HTTP {resp.status_code}: {resp.text}")
    payload = resp.json()
    if payload.get("errors"):
        raise ShopifyError(f"Shopify GraphQL errors: {payload['errors']}")
    return payload["data"]


async def _dominant_niche(client: httpx.AsyncClient) -> str:
    """Pick the niche that owns the most active products. Falls back to 'other'."""
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
        return "other"
    counts: Counter[str] = Counter()
    for edge in data["products"]["edges"]:
        ptype = (edge["node"].get("productType") or "").strip().lower()
        if ptype:
            counts[ptype] += 1
    if not counts:
        return "other"
    return counts.most_common(1)[0][0]


async def _active_theme_id(client: httpx.AsyncClient) -> int | None:
    """Return the numeric theme id of the active (role=main) theme, or None."""
    s = get_settings()
    url = f"https://{s.shopify_store_domain}/admin/api/{API_VERSION}/themes.json"
    resp = await client.get(url, headers=_headers())
    if resp.status_code >= 400:
        log.warning("themes list failed: %s", resp.text)
        return None
    for theme in resp.json().get("themes", []):
        if theme.get("role") == "main":
            return int(theme["id"])
    return None


async def _patch_theme_colors(client: httpx.AsyncClient, theme_id: int, niche: str) -> None:
    """Fetch settings_data.json, patch Dawn-style color tokens, put it back."""
    s = get_settings()
    asset_url = (
        f"https://{s.shopify_store_domain}/admin/api/{API_VERSION}/themes/{theme_id}/assets.json"
    )
    primary, accent = _palette(niche)

    # 1. GET current settings_data.json
    resp = await client.get(
        asset_url,
        headers=_headers(),
        params={"asset[key]": "config/settings_data.json"},
    )
    if resp.status_code != 200:
        log.warning("Could not fetch settings_data.json (%s): %s", resp.status_code, resp.text)
        return
    raw_value = resp.json()["asset"]["value"]
    try:
        settings = json.loads(raw_value)
    except json.JSONDecodeError:
        log.warning("settings_data.json is not valid JSON; skipping")
        return

    # 2. Patch known color keys. Dawn's structure changes across versions, so we
    # try both flat (older) and color_schemes (Dawn 9+) shapes. Unknown keys
    # are left alone.
    current = settings.get("current")
    # "current" can be a dict directly, or a preset NAME pointing into "presets".
    if isinstance(current, str) and isinstance(settings.get("presets"), dict):
        current = settings["presets"].get(current)
    if not isinstance(current, dict):
        log.warning("Theme settings shape unrecognised; skipping color patch")
        return

    patched = 0

    # Flat color tokens (older Dawn / many other themes).
    flat_map = {
        "colors_accent_1": accent,
        "colors_accent_2": accent,
        "colors_solid_button_labels": primary,
        "colors_text": accent,
        "colors_background_1": primary,
        "colors_background_2": primary,
        "color_button": accent,
        "color_button_text": primary,
    }
    for key, value in flat_map.items():
        if key in current:
            current[key] = value
            patched += 1

    # Dawn 9+ color_schemes structure.
    schemes = current.get("color_schemes")
    if isinstance(schemes, dict):
        for scheme in schemes.values():
            sset = scheme.get("settings") if isinstance(scheme, dict) else None
            if not isinstance(sset, dict):
                continue
            for bg_key in ("background", "background_gradient"):
                if bg_key in sset and isinstance(sset[bg_key], str):
                    sset[bg_key] = primary
                    patched += 1
            for fg_key in ("text", "button", "secondary_button_label", "button_label"):
                if fg_key in sset and isinstance(sset[fg_key], str):
                    sset[fg_key] = accent if "button_label" not in fg_key else primary
                    patched += 1

    if patched == 0:
        log.warning("No recognised color keys in theme settings; skipping put")
        return

    # 3. PUT updated settings_data.json
    put = await client.put(
        asset_url,
        headers=_headers(),
        json={
            "asset": {
                "key": "config/settings_data.json",
                "value": json.dumps(settings, indent=2),
            }
        },
    )
    if put.status_code >= 400:
        log.warning("Theme asset PUT failed (%s): %s", put.status_code, put.text)
        return
    log.info(
        "Theme colors patched for niche %r: primary=%s accent=%s (%d keys updated)",
        niche,
        primary,
        accent,
        patched,
    )


async def sync_store_brand() -> None:
    """Re-skin the storefront based on the dominant niche. Safe to call after each publish."""
    s = get_settings()
    if not (s.shopify_admin_token and s.shopify_store_domain):
        return
    async with httpx.AsyncClient(timeout=30) as client:
        niche = await _dominant_niche(client)
        log.info("Re-skinning storefront for dominant niche: %s", niche)
        theme_id = await _active_theme_id(client)
        if theme_id is None:
            log.warning("No main theme found - add read_themes scope to enable brand re-skinning")
            return
        try:
            await _patch_theme_colors(client, theme_id, niche)
        except Exception as exc:
            log.warning(
                "Theme color patch skipped (%s). Needs read_themes + write_themes scopes.",
                exc,
            )

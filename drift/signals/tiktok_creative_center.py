"""TikTok Creative Center adapter. Official API only - NO scraping (section 9).

Real endpoint is gated behind a TikTok For Business app. Until the token arrives,
`.fetch()` returns an empty list (NOT mock data). Mock mode is a separate adapter.
"""

from __future__ import annotations

import logging

import httpx

from drift.config import get_settings
from drift.signals.base import RawSignal, SignalAdapter
from drift.signals.google_trends import _classify_category

log = logging.getLogger(__name__)


class TikTokCreativeCenterAdapter(SignalAdapter):
    """Live TikTok Creative Center hashtag/product trends.

    Endpoint placeholder: TikTok rotates these. Update once the For Business app is approved.
    """

    BASE_URL = "https://business-api.tiktok.com/open_api/v1.3/creative_center/hashtag/trend/"

    def __init__(self, token: str | None = None) -> None:
        self.token = token or get_settings().tiktok_creative_center_token

    async def fetch(self, *, limit: int = 50) -> list[RawSignal]:
        if not self.token:
            log.info("TikTok Creative Center token missing - layer dormant")
            return []

        headers = {"Access-Token": self.token}
        params = {"period": "7", "page": 1, "limit": limit}

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(self.BASE_URL, headers=headers, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            log.warning("TikTok Creative Center fetch failed: %s", exc)
            return []

        items = (payload.get("data") or {}).get("list") or []
        out: list[RawSignal] = []
        for item in items[:limit]:
            keyword = str(item.get("hashtag_name") or item.get("name") or "").strip()
            if not keyword:
                continue
            velocity = float(item.get("trend", {}).get("rank_diff_score", 0.0))
            out.append(
                RawSignal(
                    source="tiktok_creative_center",
                    keyword=keyword,
                    category=_classify_category(keyword),
                    trend_velocity=max(-1.0, min(2.0, velocity)),
                    saturation=float(item.get("competition_score", 0.0)),
                    raw=item,
                )
            )
        return out

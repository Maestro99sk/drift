"""Google Trends adapter - live. Uses pytrends (free) when available.

Trending searches in retail categories that map cleanly to dropshipping niches.
"""

from __future__ import annotations

import asyncio
import logging

from drift.signals.base import RawSignal, SignalAdapter

log = logging.getLogger(__name__)

# Coarse Google Trends `pn` codes - keep a handful that drive most retail discovery.
TREND_GEOS: tuple[str, ...] = ("united_states", "united_kingdom", "canada", "australia")


def _classify_category(keyword: str) -> str:
    """Cheap keyword-based bucket. Good enough to feed sourcing; refined later."""
    k = keyword.lower()
    buckets = {
        "kids": ("toy", "kid", "baby", "child", "learning", "educational"),
        "fashion": ("dress", "skirt", "shoe", "bag", "jewel", "earring", "watch", "ring"),
        "beauty": ("skin", "serum", "lash", "lip", "hair", "nail", "makeup"),
        "fitness": ("gym", "yoga", "resistance", "workout", "protein"),
        "home": ("kitchen", "decor", "lamp", "rug", "cushion", "vase"),
        "pets": ("dog", "cat", "pet", "puppy", "kitten"),
        "gadgets": ("usb", "phone", "wireless", "charger", "tool", "gadget"),
    }
    for bucket, kws in buckets.items():
        if any(kw in k for kw in kws):
            return bucket
    return "other"


class GoogleTrendsAdapter(SignalAdapter):
    """Live Google Trends via pytrends."""

    def __init__(self, geos: tuple[str, ...] = TREND_GEOS) -> None:
        self.geos = geos

    async def fetch(self, *, limit: int = 50) -> list[RawSignal]:
        # pytrends is sync; offload to a worker thread so we stay async-friendly.
        return await asyncio.to_thread(self._fetch_sync, limit)

    def _fetch_sync(self, limit: int) -> list[RawSignal]:
        try:
            from pytrends.request import TrendReq
        except ImportError:
            log.warning("pytrends not installed - GoogleTrendsAdapter returning empty list")
            return []

        signals: list[RawSignal] = []
        pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 25))

        for geo in self.geos:
            try:
                df = pytrends.trending_searches(pn=geo)
            except Exception as exc:  # pytrends raises a zoo of errors
                log.warning("Google Trends fetch failed for %s: %s", geo, exc)
                continue

            for row in df.head(limit).itertuples(index=False):
                keyword = str(row[0]).strip()
                if not keyword:
                    continue
                # Trending searches don't return a velocity; we approximate from rank order
                # (top items have the strongest week-over-week rise). 1.0 at top -> 0.0 at bottom.
                rank = len(signals) % limit
                velocity = max(0.0, 1.0 - rank / max(1, limit))
                signals.append(
                    RawSignal(
                        source=f"google_trends:{geo}",
                        keyword=keyword,
                        category=_classify_category(keyword),
                        trend_velocity=velocity,
                        saturation=0.0,  # unknown; sourcing layer refines this
                        raw={"geo": geo, "rank": rank},
                    )
                )
                if len(signals) >= limit:
                    return signals

        return signals

"""Mock sourcing adapter. Returns deterministic-ish but varied results per keyword."""

from __future__ import annotations

import hashlib

from drift.sourcing.base import SourcingAdapter, SourcingResult


def _hash_float(seed: str, lo: float, hi: float) -> float:
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return lo + (h % 10_000) / 10_000 * (hi - lo)


class MockSourcingAdapter(SourcingAdapter):
    async def find(self, keyword: str, category: str) -> SourcingResult | None:
        # Simulate "unsourceable" 10% of the time so the loop sees both branches.
        if _hash_float(f"avail:{keyword}", 0, 1) < 0.1:
            return None
        unit_cost = _hash_float(f"cost:{keyword}", 2.5, 18.0)
        markup = _hash_float(f"markup:{keyword}", 2.4, 4.2)
        return SourcingResult(
            supplier="mock_cj",
            supplier_sku=f"MOCK-{abs(hash(keyword)) % 10**8}",
            unit_cost=round(unit_cost, 2),
            ship_days=int(_hash_float(f"ship:{keyword}", 7, 18)),
            reliability_score=round(_hash_float(f"rel:{keyword}", 0.6, 0.98), 3),
            stock=int(_hash_float(f"stock:{keyword}", 50, 5000)),
            suggested_sell_price=round(unit_cost * markup, 2),
            saturation=round(_hash_float(f"sat:{keyword}", 0.1, 0.85), 3),
        )

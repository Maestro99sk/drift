"""Mock signal adapter - reads tests/fixtures and produces varied candidates.

Per section 13: realistic fakes covering hot / cold / saturated / IP-reject branches so every
path of the loop gets exercised, not just the happy path.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from drift.signals.base import RawSignal, SignalAdapter

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "mock_signals.json"


class MockSignalAdapter(SignalAdapter):
    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    async def fetch(self, *, limit: int = 50) -> list[RawSignal]:
        with FIXTURE_PATH.open() as f:
            raw = json.load(f)
        signals = [
            RawSignal(
                source=f"mock:{item['source']}",
                keyword=item["keyword"],
                category=item["category"],
                trend_velocity=item["trend_velocity"],
                saturation=item["saturation"],
                raw=item,
            )
            for item in raw
        ]
        self._rng.shuffle(signals)
        return signals[:limit]

"""Signal adapter factory. Live unless MOCK_SIGNALS (or MOCK_MODE) is set."""

from __future__ import annotations

from drift.config import get_settings
from drift.signals.base import SignalAdapter


def get_signal_adapter() -> SignalAdapter:
    s = get_settings()
    if s.is_mock("signals"):
        from drift.signals.mock import MockSignalAdapter

        return MockSignalAdapter()
    # Prefer Google Trends (free, fast); TikTok Creative Center augments once token lands.
    from drift.signals.google_trends import GoogleTrendsAdapter

    return GoogleTrendsAdapter()

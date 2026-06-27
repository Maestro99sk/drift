"""Signal adapter factory. Live unless MOCK_SIGNALS (or MOCK_MODE) is set."""

from __future__ import annotations

from drift.config import get_settings
from drift.signals.base import SignalAdapter


def get_signal_adapter() -> SignalAdapter:
    """Pick a signal source.

    Order of preference:
      1. Mock (if MOCK_SIGNALS / MOCK_MODE is set) - hermetic fixtures.
      2. CJ Dropshipping bestsellers (if CJ_API_KEY is set) - real, already-sourced
         products. The right default for an active dropshipping store.
      3. Google Trends - keyword-only fallback when no supplier API is wired.
    """
    s = get_settings()
    if s.is_mock("signals"):
        from drift.signals.mock import MockSignalAdapter

        return MockSignalAdapter()

    if s.cj_api_key:
        from drift.signals.cj_hot import CJHotProductsAdapter

        return CJHotProductsAdapter()

    from drift.signals.google_trends import GoogleTrendsAdapter

    return GoogleTrendsAdapter()

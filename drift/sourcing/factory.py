from __future__ import annotations

from drift.config import get_settings
from drift.sourcing.base import SourcingAdapter


def get_sourcing_adapter() -> SourcingAdapter:
    s = get_settings()
    if s.is_mock("sourcing"):
        from drift.sourcing.mock import MockSourcingAdapter

        return MockSourcingAdapter()
    from drift.sourcing.cj import CJSourcingAdapter

    return CJSourcingAdapter()

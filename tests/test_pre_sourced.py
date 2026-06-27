"""Signals that arrive pre-sourced (CJ bestsellers) skip the sourcing lookup."""

from __future__ import annotations

import asyncio

import pytest

from drift import config
from drift.db import session_scope
from drift.models import Product
from drift.orchestrator import run_once
from drift.signals.base import RawSignal, SignalAdapter
from drift.signals import factory as signal_factory


class _PreSourcedAdapter(SignalAdapter):
    """A signal source that pretends to be CJ - every signal arrives with sourcing."""

    async def fetch(self, *, limit: int = 50) -> list[RawSignal]:
        return [
            RawSignal(
                source="cj_hot",
                keyword="kids learning wooden busy board",
                category="kids",
                trend_velocity=0.7,
                saturation=0.3,
                raw={
                    "pid": "CJ-TEST-001",
                    "pre_sourced": {
                        "supplier": "cj",
                        "supplier_sku": "CJ-TEST-001",
                        "unit_cost": 4.20,
                        "ship_days": 9,
                        "reliability_score": 0.88,
                        "stock": 1200,
                        "suggested_sell_price": 19.99,
                        "saturation": 0.3,
                    },
                },
            )
        ]


@pytest.fixture
def pre_sourced_signals(monkeypatch):
    monkeypatch.setattr(signal_factory, "get_signal_adapter", lambda: _PreSourcedAdapter())
    monkeypatch.setenv("FOCUS_CATEGORIES", "kids")
    config.get_settings.cache_clear()
    yield
    monkeypatch.delenv("FOCUS_CATEGORIES", raising=False)
    config.get_settings.cache_clear()


def test_pre_sourced_signal_creates_product_without_sourcing_lookup(pre_sourced_signals):
    result = asyncio.run(run_once())
    assert result["discovery"]["sourced"] == 1
    with session_scope() as sess:
        prod = sess.query(Product).first()
        assert prod is not None
        assert prod.supplier == "cj"
        assert prod.supplier_sku == "CJ-TEST-001"
        assert prod.unit_cost == pytest.approx(4.20)
        assert prod.est_sell_price == pytest.approx(19.99)
        assert prod.ship_days == 9

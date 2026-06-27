"""Factory routing: mock_mode wins by default; per-layer overrides take precedence."""

from __future__ import annotations

import pytest

from drift import config
from drift.dossier import get_dossier_adapter
from drift.dossier.mock import MockDossierAdapter
from drift.execution.ads import MockAdsAdapter
from drift.execution.factory import (
    get_ads_adapter,
    get_fulfilment_adapter,
    get_storefront_adapter,
)
from drift.execution.fulfilment import MockFulfilmentAdapter
from drift.execution.shopify import MockStorefrontAdapter
from drift.signals import get_signal_adapter
from drift.signals.mock import MockSignalAdapter
from drift.sourcing import get_sourcing_adapter
from drift.sourcing.mock import MockSourcingAdapter


def test_mock_mode_routes_to_mock_adapters():
    assert isinstance(get_signal_adapter(), MockSignalAdapter)
    assert isinstance(get_sourcing_adapter(), MockSourcingAdapter)
    assert isinstance(get_dossier_adapter(), MockDossierAdapter)
    assert isinstance(get_storefront_adapter(), MockStorefrontAdapter)
    assert isinstance(get_ads_adapter("meta"), MockAdsAdapter)
    assert isinstance(get_fulfilment_adapter(), MockFulfilmentAdapter)


def test_per_layer_override_unmocks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("MOCK_SIGNALS", "false")
    monkeypatch.setenv("MOCK_SOURCING", "false")
    monkeypatch.setenv("CJ_API_KEY", "fake")
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert s.is_mock("signals") is False
    assert s.is_mock("sourcing") is False
    assert s.is_mock("llm") is True  # inherits from MOCK_MODE

"""FOCUS_CATEGORIES filters surfaced candidates to a single niche."""

from __future__ import annotations

import asyncio

import pytest

from drift import config
from drift.db import session_scope
from drift.models import Candidate
from drift.orchestrator import run_once


@pytest.fixture
def kids_focus(monkeypatch):
    monkeypatch.setenv("FOCUS_CATEGORIES", "kids")
    config.get_settings.cache_clear()
    yield
    monkeypatch.delenv("FOCUS_CATEGORIES", raising=False)
    config.get_settings.cache_clear()


def test_focus_filter_drops_off_niche_signals(kids_focus):
    result = asyncio.run(run_once())
    # The off-focus stat exists and is non-zero (the home/fashion/fitness fixtures).
    assert result["discovery"]["off_focus"] >= 1
    # No non-kids candidate makes it into the DB at all (focus filter runs first).
    with session_scope() as sess:
        for c in sess.query(Candidate).all():
            assert c.category == "kids", f"non-kids candidate leaked through: {c.category}"


def test_focus_helpers_parse_csv():
    s = config.Settings(focus_categories="kids, home,  fitness")
    assert s.focus_list() == ["kids", "home", "fitness"]
    assert s.is_focused("KIDS") is True
    assert s.is_focused("fashion") is False


def test_empty_focus_allows_all():
    s = config.Settings(focus_categories="")
    assert s.focus_list() == []
    assert s.is_focused("anything") is True

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


def test_focus_keywords_substring_match():
    s = config.Settings(focus_keywords="board book, sensory, montessori")
    assert s.matches_focus_keywords("Soft Cloth Board Book for Babies") is True
    assert s.matches_focus_keywords("Sensory crinkle toy") is True
    assert s.matches_focus_keywords("Wireless car charger") is False


def test_empty_focus_keywords_allows_all():
    s = config.Settings(focus_keywords="")
    assert s.matches_focus_keywords("anything goes here") is True


def test_focus_keyword_filter_drops_off_keyword_signals(monkeypatch):
    """Category passes but keyword sub-filter rejects."""
    monkeypatch.setenv("FOCUS_CATEGORIES", "kids")
    monkeypatch.setenv("FOCUS_KEYWORDS", "board book,sensory")
    config.get_settings.cache_clear()
    try:
        result = asyncio.run(run_once())
        # All kids fixtures (busy boards, fidget toys, plush) lack 'board book'/'sensory',
        # so off_focus should be high and very few should be surfaced.
        assert result["discovery"]["off_focus"] >= 1
        with session_scope() as sess:
            for c in sess.query(Candidate).all():
                keyword = (c.raw_signal or {}).get("keyword", "").lower()
                assert (
                    "board book" in keyword or "sensory" in keyword
                ), f"keyword passed without matching focus: {keyword!r}"
    finally:
        monkeypatch.delenv("FOCUS_KEYWORDS", raising=False)
        monkeypatch.delenv("FOCUS_CATEGORIES", raising=False)
        config.get_settings.cache_clear()

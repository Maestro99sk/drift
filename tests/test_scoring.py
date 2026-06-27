from __future__ import annotations

import pytest

from drift.config import Settings
from drift.scoring.hotness import (
    HotnessInputs,
    hotness_score,
    normalise,
    should_surface,
)
from drift.scoring.ip_gate import combine_with_llm, ip_safe_keyword_check
from drift.scoring.kill_rule import DailyMetrics, breakeven_roas, evaluate_kill_rule


def _settings(**overrides: float) -> Settings:
    base = dict(
        scoring_w_trend=0.35,
        scoring_w_margin=0.25,
        scoring_w_supplier=0.25,
        scoring_w_saturation=0.15,
        scoring_surface_threshold=0.60,
        kill_roas_days=3,
        kill_trend_days=5,
    )
    base.update(overrides)
    return Settings(**base)


class TestNormalise:
    def test_basic_midpoint(self):
        assert normalise(5.0, 0.0, 10.0) == 0.5

    def test_clamps_below(self):
        assert normalise(-1.0, 0.0, 10.0) == 0.0

    def test_clamps_above(self):
        assert normalise(99.0, 0.0, 10.0) == 1.0

    def test_degenerate_range(self):
        assert normalise(5.0, 1.0, 1.0) == 0.0


class TestHotnessScore:
    def test_ip_unsafe_zeroes_everything(self):
        s = _settings()
        inputs = HotnessInputs(
            trend_velocity=2.0,
            margin_after_cac=40.0,
            supplier_reliability=1.0,
            saturation=0.0,
            ip_safe=False,
        )
        assert hotness_score(inputs, s) == 0.0

    def test_perfect_inputs_max_score(self):
        s = _settings()
        inputs = HotnessInputs(
            trend_velocity=2.0,
            margin_after_cac=40.0,
            supplier_reliability=1.0,
            saturation=0.0,
            ip_safe=True,
        )
        assert hotness_score(inputs, s) == pytest.approx(1.0)

    def test_worst_inputs_min_score(self):
        s = _settings()
        inputs = HotnessInputs(
            trend_velocity=-1.0,
            margin_after_cac=0.0,
            supplier_reliability=0.0,
            saturation=1.0,
            ip_safe=True,
        )
        assert hotness_score(inputs, s) == pytest.approx(0.0)

    def test_saturation_inverts(self):
        """Higher saturation lowers score, all else equal."""
        s = _settings()
        low_sat = HotnessInputs(0.5, 20.0, 0.8, 0.1, True)
        high_sat = HotnessInputs(0.5, 20.0, 0.8, 0.9, True)
        assert hotness_score(low_sat, s) > hotness_score(high_sat, s)

    def test_score_bounded(self):
        s = _settings()
        inputs = HotnessInputs(1.5, 30.0, 0.9, 0.2, True)
        v = hotness_score(inputs, s)
        assert 0.0 <= v <= 1.0

    def test_should_surface_threshold(self):
        s = _settings(scoring_surface_threshold=0.60)
        assert should_surface(0.61, s) is True
        assert should_surface(0.60, s) is True
        assert should_surface(0.59, s) is False


class TestIPGate:
    def test_blocks_disney(self):
        r = ip_safe_keyword_check("Disney princess plush toy")
        assert not r.safe
        assert "disney" in (r.reason or "").lower()

    def test_blocks_world_cup(self):
        r = ip_safe_keyword_check("Authentic World Cup jersey")
        assert not r.safe

    def test_blocks_fifa_word_boundary(self):
        r = ip_safe_keyword_check("FIFA collectible coin")
        assert not r.safe

    def test_allows_generic_silicone_gadget(self):
        r = ip_safe_keyword_check("Silicone collapsible measuring cup set")
        assert r.safe is True

    def test_allows_dress_style(self):
        r = ip_safe_keyword_check("Linen wrap midi dress with side pockets")
        assert r.safe is True

    def test_empty_string_fails_closed(self):
        assert ip_safe_keyword_check("").safe is False
        assert ip_safe_keyword_check("   ").safe is False

    def test_combine_with_llm_inconclusive_fails_closed(self):
        kw = ip_safe_keyword_check("plain ceramic mug")
        combined = combine_with_llm(kw, llm_safe=None, llm_reason=None)
        assert combined.safe is False

    def test_combine_with_llm_rejects(self):
        kw = ip_safe_keyword_check("plain ceramic mug")
        combined = combine_with_llm(kw, llm_safe=False, llm_reason="unlicensed mascot art")
        assert combined.safe is False
        assert "mascot" in (combined.reason or "")

    def test_combine_with_llm_both_safe(self):
        kw = ip_safe_keyword_check("plain ceramic mug")
        combined = combine_with_llm(kw, llm_safe=True, llm_reason=None)
        assert combined.safe is True

    def test_suspicious_keyword_blocks(self):
        r = ip_safe_keyword_check("OEM 1:1 replica watch")
        assert not r.safe

    def test_word_boundary_avoids_false_positives(self):
        # "apple" is blocked, but "pineapple" should not match.
        r = ip_safe_keyword_check("pineapple-shaped silicone ice mould")
        assert r.safe is True


class TestKillRule:
    def test_breakeven_roas_math(self):
        assert breakeven_roas(0.5) == 2.0
        assert breakeven_roas(0.25) == 4.0

    def test_breakeven_zero_margin(self):
        assert breakeven_roas(0.0) == float("inf")

    def test_sunset_on_roas_floor(self):
        s = _settings(kill_roas_days=3)
        # margin = 0.4 -> breakeven 2.5; 3 days at 1.5 ROAS
        history = [DailyMetrics(roas=1.5, trend_velocity=0.1, units_sold=10) for _ in range(3)]
        d = evaluate_kill_rule(history, gross_margin_fraction=0.4, settings=s)
        assert d.sunset is True
        assert "ROAS" in d.reason

    def test_no_sunset_if_one_good_day(self):
        s = _settings(kill_roas_days=3)
        history = [
            DailyMetrics(roas=1.5, trend_velocity=0.1, units_sold=10),
            DailyMetrics(roas=3.5, trend_velocity=0.1, units_sold=10),  # saved
            DailyMetrics(roas=1.5, trend_velocity=0.1, units_sold=10),
        ]
        d = evaluate_kill_rule(history, gross_margin_fraction=0.4, settings=s)
        assert d.sunset is False

    def test_sunset_on_trend_collapse(self):
        s = _settings(kill_roas_days=99, kill_trend_days=5)
        history = [
            DailyMetrics(roas=10.0, trend_velocity=-0.1, units_sold=20),
            DailyMetrics(roas=10.0, trend_velocity=-0.2, units_sold=18),
            DailyMetrics(roas=10.0, trend_velocity=-0.3, units_sold=15),
            DailyMetrics(roas=10.0, trend_velocity=-0.4, units_sold=12),
            DailyMetrics(roas=10.0, trend_velocity=-0.5, units_sold=8),
        ]
        d = evaluate_kill_rule(history, gross_margin_fraction=0.4, settings=s)
        assert d.sunset is True
        assert "trend_velocity" in d.reason

    def test_trend_alive_keeps_running(self):
        s = _settings(kill_roas_days=99, kill_trend_days=5)
        # trend still negative but units flat - does NOT meet AND condition.
        history = [
            DailyMetrics(roas=10.0, trend_velocity=-0.1, units_sold=20),
            DailyMetrics(roas=10.0, trend_velocity=-0.1, units_sold=20),
            DailyMetrics(roas=10.0, trend_velocity=-0.1, units_sold=20),
            DailyMetrics(roas=10.0, trend_velocity=-0.1, units_sold=20),
            DailyMetrics(roas=10.0, trend_velocity=-0.1, units_sold=20),
        ]
        d = evaluate_kill_rule(history, gross_margin_fraction=0.4, settings=s)
        assert d.sunset is False

    def test_short_history_never_sunsets(self):
        s = _settings()
        history = [DailyMetrics(roas=0.1, trend_velocity=-1.0, units_sold=0)]
        d = evaluate_kill_rule(history, gross_margin_fraction=0.4, settings=s)
        assert d.sunset is False

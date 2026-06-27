"""Hotness score: pure, deterministic, fully tested.

    hotness = ip_safe * (
        w_trend    * trend_velocity_norm    +
        w_margin   * margin_after_cac_norm  +
        w_supplier * supplier_reliability_norm +
        w_sat      * (1 - saturation_norm)
    )

`ip_safe` is a HARD {0,1} gate. Everything else is in [0,1]. Weights come from config.
"""

from __future__ import annotations

from dataclasses import dataclass

from drift.config import Settings, get_settings


@dataclass(frozen=True)
class HotnessInputs:
    trend_velocity: float  # rate of change of search interest, not absolute level
    margin_after_cac: float  # absolute dollars/unit after expected CAC
    supplier_reliability: float  # 0..1, blends on-time rate + review score
    saturation: float  # 0..1, share of inventory already running this product
    ip_safe: bool


def normalise(value: float, lo: float, hi: float) -> float:
    """Clamp `value` into [lo, hi], then linearly map to [0, 1]. lo==hi -> 0.0."""
    if hi <= lo:
        return 0.0
    clamped = max(lo, min(hi, value))
    return (clamped - lo) / (hi - lo)


# Normalisation reference ranges - chosen to keep production inputs inside [0, 1].
# Trend velocity is week-over-week relative change; +200%/wk is exceptional.
TREND_LO, TREND_HI = -1.0, 2.0
# Margin after CAC: $0 is breakeven floor, $40/unit is exceptional for dropshipping.
MARGIN_LO, MARGIN_HI = 0.0, 40.0


def hotness_score(inputs: HotnessInputs, settings: Settings | None = None) -> float:
    """Return the hotness score in [0, 1]. Returns 0.0 if the IP gate trips."""
    if not inputs.ip_safe:
        return 0.0
    s = settings or get_settings()

    trend_norm = normalise(inputs.trend_velocity, TREND_LO, TREND_HI)
    margin_norm = normalise(inputs.margin_after_cac, MARGIN_LO, MARGIN_HI)
    supplier_norm = max(0.0, min(1.0, inputs.supplier_reliability))
    saturation_norm = max(0.0, min(1.0, inputs.saturation))

    score = (
        s.scoring_w_trend * trend_norm
        + s.scoring_w_margin * margin_norm
        + s.scoring_w_supplier * supplier_norm
        + s.scoring_w_saturation * (1.0 - saturation_norm)
    )
    return max(0.0, min(1.0, score))


def should_surface(score: float, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return score >= s.scoring_surface_threshold

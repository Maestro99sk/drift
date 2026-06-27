"""Sunset/kill rule. Discipline as code (section 6 of CLAUDE.md).

breakeven_roas = 1 / gross_margin_fraction
sunset if (rolling_roas < breakeven_roas for >= N consecutive days)
        or (trend_velocity < 0 AND units_sold_trend < 0 for >= M consecutive days)
"""

from __future__ import annotations

from dataclasses import dataclass

from drift.config import Settings, get_settings


@dataclass(frozen=True)
class DailyMetrics:
    roas: float
    trend_velocity: float
    units_sold: int


@dataclass(frozen=True)
class KillDecision:
    sunset: bool
    reason: str


def breakeven_roas(gross_margin_fraction: float) -> float:
    if gross_margin_fraction <= 0:
        return float("inf")
    return 1.0 / gross_margin_fraction


def _units_trend_negative(window: list[DailyMetrics]) -> bool:
    """A strict day-over-day decline across the window."""
    if len(window) < 2:
        return False
    return all(window[i].units_sold < window[i - 1].units_sold for i in range(1, len(window)))


def evaluate_kill_rule(
    history: list[DailyMetrics],
    gross_margin_fraction: float,
    settings: Settings | None = None,
) -> KillDecision:
    """Return a sunset decision based on the rule above.

    `history` is ordered oldest -> newest. Only the most recent N/M days matter.
    """
    s = settings or get_settings()
    be = breakeven_roas(gross_margin_fraction)

    roas_window = history[-s.kill_roas_days :]
    if len(roas_window) >= s.kill_roas_days and all(d.roas < be for d in roas_window):
        return KillDecision(
            sunset=True,
            reason=f"ROAS < breakeven ({be:.2f}) for {s.kill_roas_days} consecutive days",
        )

    trend_window = history[-s.kill_trend_days :]
    if (
        len(trend_window) >= s.kill_trend_days
        and all(d.trend_velocity < 0 for d in trend_window)
        and _units_trend_negative(trend_window)
    ):
        return KillDecision(
            sunset=True,
            reason=f"trend_velocity < 0 and units_sold declining for {s.kill_trend_days} days",
        )

    return KillDecision(sunset=False, reason="within tolerance")

"""Scoring layer: pure deterministic functions, well tested."""

from drift.scoring.hotness import HotnessInputs, hotness_score, normalise
from drift.scoring.ip_gate import IPClassification, ip_safe_keyword_check

__all__ = [
    "HotnessInputs",
    "IPClassification",
    "hotness_score",
    "ip_safe_keyword_check",
    "normalise",
]

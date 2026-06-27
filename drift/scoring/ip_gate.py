"""IP-safety gate. Fail closed: uncertain - reject.

Two-stage check:
  1) deterministic keyword/brand blocklist (cheap, runs every candidate)
  2) optional LLM classifier check (caller can chain via `combine_with_llm`)

The deterministic stage is sufficient to reject obvious infringers and is what every
test asserts against. The LLM stage is advisory and ALSO fails closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IPClassification:
    safe: bool
    reason: str | None


# Brand and franchise names that must never appear in product titles/copy. Extend freely -
# the safer move is to add false positives than to miss a real infringer.
BLOCKED_BRANDS: tuple[str, ...] = (
    "disney",
    "marvel",
    "nintendo",
    "pokemon",
    "pokemon",
    "harry potter",
    "star wars",
    "hello kitty",
    "sanrio",
    "lego",
    "barbie",
    "minecraft",
    "fortnite",
    "roblox",
    "apple",
    "iphone",
    "ipad",
    "airpods",
    "samsung galaxy",
    "playstation",
    "xbox",
    "fifa",
    "world cup",
    "uefa",
    "premier league",
    "nba",
    "nfl",
    "mlb",
    "olympic",
    "olympics",
    "nike",
    "adidas",
    "puma",
    "gucci",
    "louis vuitton",
    "chanel",
    "rolex",
    "supreme",
    "coca-cola",
    "coca cola",
    "pepsi",
    "red bull",
    "taylor swift",
    "kardashian",
    "beyonce",
    "beyonce",
    "messi",
    "ronaldo",
    "lebron",
    "netflix",
    "hbo",
    "spotify",
    "youtube",
    "tiktok",
    "spider-man",
    "spiderman",
    "batman",
    "superman",
    "avengers",
    "frozen",
)

BLOCKED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"(?<![a-z0-9]){re.escape(b)}(?![a-z0-9])", re.IGNORECASE) for b in BLOCKED_BRANDS
)

# Single-word "danger zones" that frequently indicate counterfeit or licensed merch.
SUSPICIOUS_KEYWORDS: tuple[str, ...] = (
    "official",
    "licensed",
    "authentic replica",
    "1:1 replica",
    "oem",
    "branded jersey",
    "team kit",
    "movie merch",
    "anime merch",
)


def ip_safe_keyword_check(text: str) -> IPClassification:
    """Return (safe, reason). Empty text fails closed."""
    if not text or not text.strip():
        return IPClassification(safe=False, reason="empty text - fail closed")

    haystack = text.lower()
    for pat in BLOCKED_PATTERNS:
        m = pat.search(haystack)
        if m:
            return IPClassification(safe=False, reason=f"blocked brand: {m.group(0)}")

    for kw in SUSPICIOUS_KEYWORDS:
        if kw in haystack:
            return IPClassification(safe=False, reason=f"suspicious keyword: {kw}")

    return IPClassification(safe=True, reason=None)


def combine_with_llm(
    keyword_result: IPClassification, llm_safe: bool | None, llm_reason: str | None
) -> IPClassification:
    """Both stages must agree on `safe=True`. Anything else trips the gate."""
    if not keyword_result.safe:
        return keyword_result
    if llm_safe is None:
        return IPClassification(safe=False, reason="LLM check inconclusive - fail closed")
    if not llm_safe:
        return IPClassification(safe=False, reason=llm_reason or "LLM classifier flagged")
    return IPClassification(safe=True, reason=None)

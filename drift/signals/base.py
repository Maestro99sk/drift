"""Signal adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawSignal:
    source: str
    keyword: str
    category: str
    trend_velocity: float  # rate of change (week-over-week, normalised to ~[-1, +2])
    saturation: float  # 0..1, share of competitor sellers running this product
    raw: dict[str, Any] = field(default_factory=dict)


class SignalAdapter(ABC):
    """All signal sources implement this."""

    @abstractmethod
    async def fetch(self, *, limit: int = 50) -> list[RawSignal]: ...

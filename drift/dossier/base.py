from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DossierInputs:
    keyword: str
    category: str
    trend_velocity: float
    saturation: float
    unit_cost: float
    suggested_sell_price: float
    ship_days: int
    reliability_score: float


@dataclass(frozen=True)
class DossierDraft:
    ad_angle: str
    copy: str
    projected_unit_economics: dict[str, Any] = field(default_factory=dict)
    ip_llm_safe: bool | None = None
    ip_llm_reason: str | None = None


class DossierAdapter(ABC):
    @abstractmethod
    async def generate(self, inputs: DossierInputs) -> DossierDraft: ...

    @abstractmethod
    async def classify_ip(self, text: str) -> tuple[bool | None, str | None]: ...

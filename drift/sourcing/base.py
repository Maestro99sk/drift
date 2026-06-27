"""Sourcing adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SourcingResult:
    supplier: str
    supplier_sku: str
    unit_cost: float
    ship_days: int
    reliability_score: float  # 0..1, on-time rate * review score
    stock: int
    suggested_sell_price: float
    saturation: float  # estimated competitor density for this SKU


class SourcingAdapter(ABC):
    @abstractmethod
    async def find(self, keyword: str, category: str) -> SourcingResult | None: ...

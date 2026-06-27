from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PublishResult:
    external_id: str
    storefront_url: str


@dataclass(frozen=True)
class CampaignResult:
    platform: str
    external_id: str


@dataclass(frozen=True)
class FulfilmentResult:
    supplier_order_id: str
    status: str  # "submitted" | "failed"


class StorefrontAdapter(ABC):
    @abstractmethod
    async def publish(
        self,
        *,
        title: str,
        body_html: str,
        price: float,
        sku: str,
        niche_theme: str,
        utm_key: str,
    ) -> PublishResult: ...


class AdsAdapter(ABC):
    @abstractmethod
    async def launch(
        self,
        *,
        product_id: int,
        landing_url: str,
        ad_angle: str,
        daily_budget: float,
    ) -> CampaignResult: ...

    @abstractmethod
    async def pause(self, external_id: str) -> None: ...


class FulfilmentAdapter(ABC):
    @abstractmethod
    async def submit(
        self,
        *,
        supplier_sku: str,
        quantity: int,
        ship_to: dict,
    ) -> FulfilmentResult: ...

"""Core data model. SQLModel for persistence; pure Pydantic mixins for clarity."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlmodel import JSON, Column, Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CandidateStatus(StrEnum):
    NEW = "new"
    SOURCED = "sourced"
    SCORED = "scored"
    SURFACED = "surfaced"
    APPROVED = "approved"
    REJECTED = "rejected"
    LIVE = "live"
    SUNSET = "sunset"


class DossierStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class DecisionType(StrEnum):
    KEEP = "keep"
    SCALE = "scale"
    SUNSET = "sunset"


class Candidate(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source: str
    raw_signal: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    category: str
    trend_velocity: float = 0.0
    saturation: float = 0.0
    ip_risk_flag: bool = False
    ip_risk_reason: str | None = None
    status: CandidateStatus = Field(default=CandidateStatus.NEW)
    is_mock: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id")
    supplier: str
    supplier_sku: str
    unit_cost: float
    ship_days: int
    reliability_score: float
    est_sell_price: float
    est_margin: float
    stock: int = 0
    is_mock: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class Dossier(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    hotness: float
    projected_unit_economics: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    ad_angle: str
    body_copy: str
    status: DossierStatus = Field(default=DossierStatus.DRAFT)
    owner_edits: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    is_mock: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class LandingPage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    niche_theme: str
    utm_key: str = Field(index=True, unique=True)
    storefront_url: str | None = None
    is_mock: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class Campaign(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    platform: str  # "meta" | "tiktok"
    daily_budget: float
    status: str  # "active" | "paused" | "ended"
    external_id: str | None = None
    is_mock: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class MetricSnapshot(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    ts: datetime = Field(default_factory=_utcnow, index=True)
    units_sold: int = 0
    revenue: float = 0.0
    ad_spend: float = 0.0
    roas: float = 0.0
    trend_velocity: float = 0.0
    is_mock: bool = False


class Decision(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    ts: datetime = Field(default_factory=_utcnow)
    type: DecisionType
    reason: str
    is_mock: bool = False


class Settings(SQLModel, table=True):
    """Runtime-mutable settings, separate from the env-driven Settings class."""

    key: str = Field(primary_key=True)
    value: str

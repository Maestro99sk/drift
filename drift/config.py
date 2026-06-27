"""Centralised configuration. All env-driven; never hardcode secrets."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM ---
    anthropic_api_key: str = ""
    llm_filter_model: str = "claude-haiku-4-5"
    llm_dossier_model: str = "claude-sonnet-4-6"
    llm_strategy_model: str = "claude-opus-4-8"
    llm_max_tokens: int = 2048

    # --- Signals ---
    serpapi_key: str = ""
    tiktok_creative_center_token: str = ""

    # --- Sourcing ---
    cj_api_key: str = ""

    # --- Storefront ---
    shopify_admin_token: str = ""
    shopify_store_domain: str = ""
    # Used only by `drift shopify-install` to fetch a permanent admin token via OAuth.
    shopify_client_id: str = ""
    shopify_client_secret: str = ""
    shopify_scopes: str = "write_products,read_products"
    shopify_install_callback_host: str = "0.0.0.0"
    shopify_install_callback_port: int = 8765
    # What Shopify sees as the redirect URL (must exactly match a URL allow-listed
    # in the app's Redirect URLs config). Defaults to localhost; override if running
    # on a remote server.
    shopify_install_redirect_url: str = "http://localhost:8765/callback"

    # --- Ads ---
    meta_marketing_token: str = ""
    meta_ad_account_id: str = ""
    tiktok_marketing_token: str = ""
    tiktok_advertiser_id: str = ""

    # --- Persistence ---
    database_url: str = "sqlite:///drift.db"

    # --- Mock mode ---
    mock_mode: bool = False
    mock_signals: bool | None = None
    mock_sourcing: bool | None = None
    mock_llm: bool | None = None
    mock_storefront: bool | None = None
    mock_ads: bool | None = None
    mock_fulfilment: bool | None = None

    # --- Scoring ---
    scoring_w_trend: float = 0.35
    scoring_w_margin: float = 0.25
    scoring_w_supplier: float = 0.25
    scoring_w_saturation: float = 0.15
    scoring_surface_threshold: float = 0.60

    # --- Kill rule ---
    kill_roas_days: int = 3
    kill_trend_days: int = 5

    # --- Loop ---
    loop_interval_seconds: int = Field(default=900, description="Orchestrator tick interval")

    # --- Focus mode ---
    # Comma-separated list of categories the loop is allowed to surface.
    # Empty string = all categories (the original multi-niche behaviour).
    # Single value (e.g. "kids") locks the store to one niche - cleaner branding,
    # one ad account, one creative voice. The engine still supports the rest;
    # they just sit dormant until you widen the list.
    focus_categories: str = ""
    # Comma-separated must-contain keywords applied AFTER focus_categories.
    # Lets you go sub-niche: focus_categories=kids + focus_keywords=board book,
    # sensory book, cloth book -> only baby/toddler learning books surface.
    # Empty = no keyword filter.
    focus_keywords: str = ""

    def focus_list(self) -> list[str]:
        return [c.strip().lower() for c in self.focus_categories.split(",") if c.strip()]

    def focus_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.focus_keywords.split(",") if k.strip()]

    def is_focused(self, category: str) -> bool:
        focus = self.focus_list()
        return not focus or category.lower() in focus

    def matches_focus_keywords(self, text: str) -> bool:
        kws = self.focus_keyword_list()
        if not kws:
            return True
        haystack = text.lower()
        return any(kw in haystack for kw in kws)

    @field_validator(
        "scoring_w_trend", "scoring_w_margin", "scoring_w_supplier", "scoring_w_saturation"
    )
    @classmethod
    def _weights_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("scoring weights must be in [0, 1]")
        return v

    @field_validator(
        "mock_signals",
        "mock_sourcing",
        "mock_llm",
        "mock_storefront",
        "mock_ads",
        "mock_fulfilment",
        mode="before",
    )
    @classmethod
    def _blank_mock_is_none(cls, v: object) -> object:
        # `.env` lines like `MOCK_SIGNALS=` mean "inherit MOCK_MODE", not "fail to parse".
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # --- Per-layer mock resolution ---
    def is_mock(self, layer: str) -> bool:
        layer_attr = f"mock_{layer}"
        if not hasattr(self, layer_attr):
            raise ValueError(f"unknown layer: {layer}")
        override = getattr(self, layer_attr)
        return self.mock_mode if override is None else override

    def any_mocked(self) -> list[str]:
        layers = ["signals", "sourcing", "llm", "storefront", "ads", "fulfilment"]
        return [layer for layer in layers if self.is_mock(layer)]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Drop the cache - useful when the dashboard flips mock toggles at runtime."""
    get_settings.cache_clear()
    return get_settings()

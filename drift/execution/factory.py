from __future__ import annotations

from drift.config import get_settings
from drift.execution.ads import AdsAdapter, MetaAdsAdapter, MockAdsAdapter, TikTokAdsAdapter
from drift.execution.base import FulfilmentAdapter, StorefrontAdapter
from drift.execution.fulfilment import CJFulfilmentAdapter, MockFulfilmentAdapter
from drift.execution.shopify import MockStorefrontAdapter, ShopifyStorefrontAdapter


def get_storefront_adapter() -> StorefrontAdapter:
    s = get_settings()
    if s.is_mock("storefront") or not (s.shopify_admin_token and s.shopify_store_domain):
        return MockStorefrontAdapter()
    return ShopifyStorefrontAdapter()


def get_ads_adapter(platform: str = "meta") -> AdsAdapter:
    s = get_settings()
    if s.is_mock("ads"):
        return MockAdsAdapter()
    if platform == "meta":
        if not (s.meta_marketing_token and s.meta_ad_account_id):
            return MockAdsAdapter()
        return MetaAdsAdapter()
    if platform == "tiktok":
        if not (s.tiktok_marketing_token and s.tiktok_advertiser_id):
            return MockAdsAdapter()
        return TikTokAdsAdapter()
    raise ValueError(f"unknown ad platform: {platform}")


def get_fulfilment_adapter() -> FulfilmentAdapter:
    s = get_settings()
    if s.is_mock("fulfilment") or not s.cj_api_key:
        return MockFulfilmentAdapter()
    return CJFulfilmentAdapter()

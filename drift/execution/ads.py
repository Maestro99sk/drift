"""Ad-platform adapters. Meta + TikTok. Both require approved business accounts."""

from __future__ import annotations

import logging

import httpx

from drift.config import get_settings
from drift.execution.base import AdsAdapter, CampaignResult

log = logging.getLogger(__name__)


class MetaAdsAdapter(AdsAdapter):
    """Meta Marketing API. Requires META_MARKETING_TOKEN + META_AD_ACCOUNT_ID."""

    GRAPH = "https://graph.facebook.com/v20.0"

    def __init__(self) -> None:
        s = get_settings()
        self.token = s.meta_marketing_token
        self.account_id = s.meta_ad_account_id

    async def launch(
        self,
        *,
        product_id: int,
        landing_url: str,
        ad_angle: str,
        daily_budget: float,
    ) -> CampaignResult:
        if not (self.token and self.account_id):
            raise RuntimeError("Meta credentials missing - ads dormant")

        payload = {
            "name": f"drift-product-{product_id}",
            "objective": "OUTCOME_SALES",
            "status": "PAUSED",  # human-in-the-loop: caller flips to ACTIVE explicitly
            "special_ad_categories": "[]",
            "daily_budget": int(daily_budget * 100),  # cents
            "access_token": self.token,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(f"{self.GRAPH}/act_{self.account_id}/campaigns", data=payload)
            resp.raise_for_status()
            data = resp.json()
        # NB: a full launch creates AdSet + AdCreative + Ad. We return the campaign id;
        # the rest is composed by `monitoring` once the owner approves activation.
        return CampaignResult(platform="meta", external_id=str(data["id"]))

    async def pause(self, external_id: str) -> None:
        if not self.token:
            return
        async with httpx.AsyncClient(timeout=20) as client:
            await client.post(
                f"{self.GRAPH}/{external_id}",
                data={"status": "PAUSED", "access_token": self.token},
            )


class TikTokAdsAdapter(AdsAdapter):
    """TikTok Marketing API."""

    BASE = "https://business-api.tiktok.com/open_api/v1.3"

    def __init__(self) -> None:
        s = get_settings()
        self.token = s.tiktok_marketing_token
        self.advertiser_id = s.tiktok_advertiser_id

    async def launch(
        self,
        *,
        product_id: int,
        landing_url: str,
        ad_angle: str,
        daily_budget: float,
    ) -> CampaignResult:
        if not (self.token and self.advertiser_id):
            raise RuntimeError("TikTok credentials missing - ads dormant")

        payload = {
            "advertiser_id": self.advertiser_id,
            "campaign_name": f"drift-product-{product_id}",
            "objective_type": "CONVERSIONS",
            "budget_mode": "BUDGET_MODE_DAY",
            "budget": daily_budget,
            "operation_status": "DISABLE",  # human flips to ENABLE explicitly
        }
        headers = {"Access-Token": self.token}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(f"{self.BASE}/campaign/create/", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json().get("data", {})
        return CampaignResult(platform="tiktok", external_id=str(data.get("campaign_id", "")))

    async def pause(self, external_id: str) -> None:
        if not (self.token and self.advertiser_id):
            return
        headers = {"Access-Token": self.token}
        payload = {
            "advertiser_id": self.advertiser_id,
            "campaign_ids": [external_id],
            "operation_status": "DISABLE",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            await client.post(f"{self.BASE}/campaign/status/update/", headers=headers, json=payload)


class MockAdsAdapter(AdsAdapter):
    async def launch(self, *, product_id, landing_url, ad_angle, daily_budget):
        return CampaignResult(platform="mock", external_id=f"mock-ad-{product_id}")

    async def pause(self, external_id: str) -> None:
        return

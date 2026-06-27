"""Loop orchestrator: signal -> source -> score -> dossier (DRAFT) -> save to DB.

Surfaces candidates >= surface_threshold for owner review on the dashboard. Execution
(publish + ads + fulfilment) only fires after explicit approval in the dashboard.
"""

from __future__ import annotations

import asyncio
import logging

from drift.config import get_settings
from drift.db import init_db, session_scope
from drift.dossier import get_dossier_adapter
from drift.dossier.base import DossierInputs
from drift.models import (
    Candidate,
    CandidateStatus,
    Dossier,
    DossierStatus,
    Product,
)
from drift.monitoring import evaluate_and_act, snapshot_metrics
from drift.scoring.hotness import HotnessInputs, hotness_score, should_surface
from drift.scoring.ip_gate import combine_with_llm, ip_safe_keyword_check
from drift.signals import get_signal_adapter
from drift.sourcing import get_sourcing_adapter

log = logging.getLogger(__name__)


async def discovery_tick() -> dict:
    """One pass: pull signals, source, score, draft dossiers for surfaced candidates."""
    settings = get_settings()
    signals = await get_signal_adapter().fetch(limit=30)
    sourcing = get_sourcing_adapter()
    dossier_adapter = get_dossier_adapter()

    stats = {
        "signals": len(signals),
        "sourced": 0,
        "scored": 0,
        "surfaced": 0,
        "ip_rejected": 0,
        "off_focus": 0,
    }

    for sig in signals:
        # Focus-mode filters: category first, then keyword sub-filter for sub-niches.
        if not settings.is_focused(sig.category):
            stats["off_focus"] += 1
            continue
        if not settings.matches_focus_keywords(sig.keyword):
            stats["off_focus"] += 1
            continue
        # Stage 1: deterministic IP keyword check (cheap, runs on every candidate).
        kw_result = ip_safe_keyword_check(sig.keyword)
        ip_safe = kw_result.safe
        ip_reason = kw_result.reason

        # Stage 2: LLM IP classifier - only if keyword stage passes (saves spend).
        if ip_safe:
            llm_safe, llm_reason = await dossier_adapter.classify_ip(sig.keyword)
            combined = combine_with_llm(kw_result, llm_safe, llm_reason)
            ip_safe = combined.safe
            ip_reason = combined.reason

        sourced = None
        if ip_safe:
            # Pre-sourced signals (e.g. from CJ bestsellers) ship the supplier
            # data alongside the signal - no second lookup needed.
            pre = sig.raw.get("pre_sourced") if isinstance(sig.raw, dict) else None
            if isinstance(pre, dict):
                from drift.sourcing.base import SourcingResult

                sourced = SourcingResult(
                    supplier=pre.get("supplier", "unknown"),
                    supplier_sku=str(pre["supplier_sku"]),
                    unit_cost=float(pre["unit_cost"]),
                    ship_days=int(pre.get("ship_days", 12)),
                    reliability_score=float(pre.get("reliability_score", 0.7)),
                    stock=int(pre.get("stock", 0)),
                    suggested_sell_price=float(pre["suggested_sell_price"]),
                    saturation=float(pre.get("saturation", sig.saturation)),
                )
            else:
                sourced = await sourcing.find(sig.keyword, sig.category)
            if sourced is None:
                continue
            stats["sourced"] += 1

        # If IP gate failed, we still record the rejection for auditability.
        with session_scope() as sess:
            cand = Candidate(
                source=sig.source,
                raw_signal=sig.raw,
                category=sig.category,
                trend_velocity=sig.trend_velocity,
                saturation=sourced.saturation if sourced else sig.saturation,
                ip_risk_flag=not ip_safe,
                ip_risk_reason=ip_reason,
                status=CandidateStatus.REJECTED if not ip_safe else CandidateStatus.SOURCED,
                is_mock=settings.is_mock("signals"),
            )
            sess.add(cand)
            sess.flush()
            candidate_id = cand.id

            if not ip_safe:
                stats["ip_rejected"] += 1
                continue

            assert sourced is not None
            margin_after_cac = sourced.suggested_sell_price - sourced.unit_cost - 8.0
            product = Product(
                candidate_id=candidate_id,
                supplier=sourced.supplier,
                supplier_sku=sourced.supplier_sku,
                unit_cost=sourced.unit_cost,
                ship_days=sourced.ship_days,
                reliability_score=sourced.reliability_score,
                est_sell_price=sourced.suggested_sell_price,
                est_margin=sourced.suggested_sell_price - sourced.unit_cost,
                stock=sourced.stock,
                is_mock=settings.is_mock("sourcing"),
            )
            sess.add(product)
            sess.flush()

            score = hotness_score(
                HotnessInputs(
                    trend_velocity=sig.trend_velocity,
                    margin_after_cac=margin_after_cac,
                    supplier_reliability=sourced.reliability_score,
                    saturation=sourced.saturation,
                    ip_safe=True,
                )
            )
            cand.status = CandidateStatus.SCORED
            sess.add(cand)
            stats["scored"] += 1

            if should_surface(score):
                draft = await dossier_adapter.generate(
                    DossierInputs(
                        keyword=sig.keyword,
                        category=sig.category,
                        trend_velocity=sig.trend_velocity,
                        saturation=sourced.saturation,
                        unit_cost=sourced.unit_cost,
                        suggested_sell_price=sourced.suggested_sell_price,
                        ship_days=sourced.ship_days,
                        reliability_score=sourced.reliability_score,
                    )
                )
                dossier = Dossier(
                    product_id=product.id,
                    hotness=score,
                    projected_unit_economics=draft.projected_unit_economics,
                    ad_angle=draft.ad_angle,
                    body_copy=draft.copy,
                    status=DossierStatus.DRAFT,
                    is_mock=settings.is_mock("llm"),
                )
                sess.add(dossier)
                cand.status = CandidateStatus.SURFACED
                sess.add(cand)
                stats["surfaced"] += 1

    return stats


async def monitoring_tick() -> dict:
    """Snapshot metrics and run rotation/kill logic on live products."""
    snaps = snapshot_metrics()
    decisions = await evaluate_and_act()
    return {
        "snapshots": snaps,
        "decisions": len(decisions),
        "sunsets": sum(1 for d in decisions if d.get("type") == "sunset"),
    }


async def run_once() -> dict:
    init_db()
    discovery = await discovery_tick()
    monitoring = await monitoring_tick()
    return {"discovery": discovery, "monitoring": monitoring}


def run_loop() -> None:
    """Run forever on APScheduler. Use this for long-running deployments."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    settings = get_settings()
    init_db()
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        lambda: asyncio.run(_safe_run_once()),
        "interval",
        seconds=settings.loop_interval_seconds,
        next_run_time=None,
    )
    log.info("Drift loop starting; interval=%ss", settings.loop_interval_seconds)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Drift loop stopped")


async def _safe_run_once() -> None:
    try:
        result = await run_once()
        log.info("Tick OK: %s", result)
    except Exception:
        log.exception("Tick failed")


async def approve_dossier(dossier_id: int) -> dict:
    """Owner hits Approve. Publish storefront, draft (paused) ad campaigns."""
    from drift.execution import get_ads_adapter, get_storefront_adapter
    from drift.models import Campaign, LandingPage

    settings = get_settings()
    with session_scope() as sess:
        d = sess.get(Dossier, dossier_id)
        if not d:
            raise ValueError(f"dossier {dossier_id} not found")
        product = sess.get(Product, d.product_id)
        if not product:
            raise ValueError("product missing")
        cand = sess.get(Candidate, product.candidate_id)
        if not cand:
            raise ValueError("candidate missing")

        storefront = get_storefront_adapter()
        utm_key = f"d{dossier_id}-{cand.category}"
        publish_result = await storefront.publish(
            title=cand.raw_signal.get("keyword", f"Drift #{dossier_id}"),
            body_html=d.body_copy,
            price=product.est_sell_price,
            sku=product.supplier_sku,
            niche_theme=cand.category,
            utm_key=utm_key,
        )

        landing = LandingPage(
            product_id=product.id,
            niche_theme=cand.category,
            utm_key=utm_key,
            storefront_url=publish_result.storefront_url,
            is_mock=settings.is_mock("storefront"),
        )
        sess.add(landing)

        # Draft (PAUSED) campaigns on both platforms; human flips them live separately.
        for platform in ("meta", "tiktok"):
            try:
                ads = get_ads_adapter(platform)
                cr = await ads.launch(
                    product_id=product.id,
                    landing_url=publish_result.storefront_url,
                    ad_angle=d.ad_angle,
                    daily_budget=10.0,
                )
                sess.add(
                    Campaign(
                        product_id=product.id,
                        platform=cr.platform,
                        daily_budget=10.0,
                        status="paused",  # human flips to active explicitly
                        external_id=cr.external_id,
                        is_mock=settings.is_mock("ads"),
                    )
                )
            except RuntimeError as exc:
                log.info("Skipping %s campaign creation: %s", platform, exc)

        d.status = DossierStatus.APPROVED
        sess.add(d)
        cand.status = CandidateStatus.LIVE
        sess.add(cand)

    # Re-skin the storefront based on the now-dominant niche. Runs outside the
    # session scope so a brand-API hiccup never blocks an otherwise good publish.
    if not settings.is_mock("storefront"):
        try:
            from drift.execution.store_brand import sync_store_brand

            await sync_store_brand()
        except Exception as exc:
            log.warning("Store brand sync skipped: %s", exc)

    return {
        "dossier_id": dossier_id,
        "storefront_url": publish_result.storefront_url,
        "utm_key": utm_key,
    }


def reject_dossier(dossier_id: int, reason: str = "") -> None:
    with session_scope() as sess:
        d = sess.get(Dossier, dossier_id)
        if not d:
            raise ValueError(f"dossier {dossier_id} not found")
        d.status = DossierStatus.REJECTED
        d.owner_edits = {**(d.owner_edits or {}), "rejection_reason": reason}
        sess.add(d)
        cand_product = sess.get(Product, d.product_id)
        if cand_product:
            cand = sess.get(Candidate, cand_product.candidate_id)
            if cand:
                cand.status = CandidateStatus.REJECTED
                sess.add(cand)

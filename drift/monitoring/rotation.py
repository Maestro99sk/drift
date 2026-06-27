"""Closes the loop: snapshot metrics for live products, apply kill rule, sunset, surface next.

Live metric sources (Shopify orders, Meta/TikTok insights) are pluggable. Until those
adapters are wired with real credentials, the snapshot reads zeros for real products and
synthesised numbers for mock products.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from drift.config import get_settings
from drift.db import session_scope
from drift.execution.factory import get_ads_adapter
from drift.models import (
    Campaign,
    CandidateStatus,
    Decision,
    DecisionType,
    Dossier,
    DossierStatus,
    MetricSnapshot,
    Product,
)
from drift.scoring.kill_rule import DailyMetrics, evaluate_kill_rule

log = logging.getLogger(__name__)


def _mock_metric(product_id: int, day: int) -> tuple[float, float, int]:
    """Synthesise a plausible day for a mock product: cold products decay, hot ones grow."""
    h = int(hashlib.sha256(f"{product_id}".encode()).hexdigest(), 16) % 100
    base_roas = 1.5 + (h % 30) / 10.0  # 1.5..4.5
    trend = (h - 50) / 100.0  # -0.5..+0.5
    roas = max(0.0, base_roas + trend * day)
    velocity = trend - day * 0.05
    units = max(0, int(20 + trend * 10 - day * 2))
    return roas, velocity, units


def snapshot_metrics(now: datetime | None = None) -> int:
    """Take a MetricSnapshot per live product. Returns count of snapshots written."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    count = 0
    with session_scope() as sess:
        live_products = sess.exec(
            select(Product)
            .join(Dossier, Dossier.product_id == Product.id)
            .where(Dossier.status == DossierStatus.APPROVED)
        ).all()
        for p in live_products:
            if p.is_mock or any(settings.is_mock(layer) for layer in ("ads", "fulfilment")):
                roas, velocity, units = _mock_metric(p.id or 0, 0)
                snap = MetricSnapshot(
                    product_id=p.id,
                    ts=now,
                    units_sold=units,
                    revenue=units * p.est_sell_price,
                    ad_spend=(units * p.est_sell_price) / max(0.01, roas),
                    roas=roas,
                    trend_velocity=velocity,
                    is_mock=True,
                )
            else:
                # COMPLIANCE TODO: pull true insights from Meta/TikTok + Shopify orders.
                # Until credentials land, write a zero snapshot so the loop is observable.
                snap = MetricSnapshot(
                    product_id=p.id,
                    ts=now,
                    units_sold=0,
                    revenue=0.0,
                    ad_spend=0.0,
                    roas=0.0,
                    trend_velocity=0.0,
                    is_mock=False,
                )
            sess.add(snap)
            count += 1
    return count


async def evaluate_and_act() -> list[dict]:
    """Apply kill rule to every live product; pause ads + flag candidate on sunset.

    Returns plain dicts (not ORM objects) so callers can safely read the result
    after the DB session has been committed and the SQLAlchemy instances
    detached.
    """
    from drift.models import Candidate

    decisions: list[dict] = []
    settings = get_settings()
    cutoff_days = max(settings.kill_roas_days, settings.kill_trend_days)
    cutoff = datetime.now(UTC) - timedelta(days=cutoff_days + 1)

    # Pull what we need from the DB first, then run async side-effects, then commit.
    pause_tasks: list[tuple[int, str, str]] = []  # (campaign_id, platform, external_id)
    with session_scope() as sess:
        live_products = sess.exec(
            select(Product)
            .join(Dossier, Dossier.product_id == Product.id)
            .where(Dossier.status == DossierStatus.APPROVED)
        ).all()
        for p in live_products:
            snaps = sess.exec(
                select(MetricSnapshot)
                .where(MetricSnapshot.product_id == p.id)
                .where(MetricSnapshot.ts >= cutoff)
                .order_by(MetricSnapshot.ts)
            ).all()
            if not snaps:
                continue
            history = [
                DailyMetrics(roas=s.roas, trend_velocity=s.trend_velocity, units_sold=s.units_sold)
                for s in snaps
            ]
            gm_frac = (
                (p.est_sell_price - p.unit_cost) / p.est_sell_price if p.est_sell_price else 0.0
            )
            decision = evaluate_kill_rule(history, gross_margin_fraction=gm_frac, settings=settings)
            if decision.sunset:
                campaigns = sess.exec(select(Campaign).where(Campaign.product_id == p.id)).all()
                for c in campaigns:
                    if c.status != "paused" and c.external_id:
                        pause_tasks.append((c.id or 0, c.platform, c.external_id))
                    c.status = "paused"
                    sess.add(c)
                cand = sess.get(Candidate, p.candidate_id)
                if cand:
                    cand.status = CandidateStatus.SUNSET
                    sess.add(cand)
                d = Decision(
                    product_id=p.id,
                    type=DecisionType.SUNSET,
                    reason=decision.reason,
                    is_mock=p.is_mock,
                )
                sess.add(d)
                decisions.append({"product_id": p.id, "type": "sunset", "reason": decision.reason})
            else:
                d = Decision(
                    product_id=p.id,
                    type=DecisionType.KEEP,
                    reason=decision.reason,
                    is_mock=p.is_mock,
                )
                sess.add(d)
                decisions.append({"product_id": p.id, "type": "keep", "reason": decision.reason})

    # Run ad-platform pauses concurrently outside the DB session.
    for _cid, platform, external_id in pause_tasks:
        try:
            ads = get_ads_adapter(platform)
            await ads.pause(external_id)
        except Exception as exc:
            log.warning("Failed to pause %s campaign %s: %s", platform, external_id, exc)
    return decisions

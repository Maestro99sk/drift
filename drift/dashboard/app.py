"""Streamlit owner dashboard. Mock-mode banner, surfaced candidates, approve/reject."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import streamlit as st
from sqlmodel import select

from drift.config import get_settings, reload_settings
from drift.db import init_db, session_scope
from drift.models import (
    Candidate,
    Decision,
    Dossier,
    DossierStatus,
    MetricSnapshot,
    Product,
)
from drift.orchestrator import approve_dossier, reject_dossier, run_once

st.set_page_config(page_title="Drift - Owner Console", layout="wide")
init_db()


def _mock_banner() -> None:
    s = get_settings()
    mocked = s.any_mocked()
    if mocked:
        st.warning(
            f"-  **MOCK MODE - {', '.join(mocked)}.** "
            "Mock records are tagged `is_mock=true` and excluded from real ROAS/scoring calibration.",
            icon="- ",
        )


def _mock_sidebar() -> None:
    s = get_settings()
    st.sidebar.header("Mock-mode controls")
    st.sidebar.caption("Live is the default. Toggling a layer mocks ONLY that boundary.")
    master = st.sidebar.toggle("Master MOCK_MODE", value=s.mock_mode, key="mm")
    os.environ["MOCK_MODE"] = "true" if master else "false"
    for layer in ("signals", "sourcing", "llm", "storefront", "ads", "fulfilment"):
        cur = s.is_mock(layer)
        val = st.sidebar.toggle(f"mock_{layer}", value=cur, key=f"m_{layer}")
        os.environ[f"MOCK_{layer.upper()}"] = "true" if val else "false"
    if st.sidebar.button("Apply"):
        reload_settings()
        st.rerun()


def _surfaced_table() -> None:
    st.subheader("Surfaced candidates (awaiting approval)")
    with session_scope() as sess:
        rows = sess.exec(
            select(Dossier, Product, Candidate)
            .join(Product, Product.id == Dossier.product_id)
            .join(Candidate, Candidate.id == Product.candidate_id)
            .where(Dossier.status == DossierStatus.DRAFT)
            .order_by(Dossier.hotness.desc())
        ).all()
        if not rows:
            st.info("No surfaced candidates yet. Run a discovery tick (button below).")
            return
        for dossier, product, candidate in rows:
            with st.expander(
                f"#{dossier.id} * {candidate.raw_signal.get('keyword', '?')} * "
                f"hotness {dossier.hotness:.2f} * {'MOCK' if dossier.is_mock else 'LIVE'}"
            ):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown(f"**Category:** {candidate.category}")
                    st.markdown(f"**Supplier:** {product.supplier} * SKU `{product.supplier_sku}`")
                    st.markdown(
                        f"**Unit cost:** ${product.unit_cost:.2f} * "
                        f"**Sell:** ${product.est_sell_price:.2f} * "
                        f"**Ship days:** {product.ship_days}"
                    )
                    st.markdown(f"**Reliability:** {product.reliability_score:.2f}")
                with col_b:
                    st.markdown("**Ad angle:**")
                    st.write(dossier.ad_angle)
                    st.markdown("**Copy:**")
                    st.write(dossier.body_copy)
                    st.markdown("**Projected economics:**")
                    st.json(dossier.projected_unit_economics or {})

                edit_copy = st.text_area(
                    "Edit copy before publish",
                    value=dossier.body_copy,
                    key=f"copy_{dossier.id}",
                )
                c1, c2 = st.columns(2)
                if c1.button("Approve & publish", key=f"app_{dossier.id}", type="primary"):
                    if edit_copy != dossier.body_copy:
                        dossier.body_copy = edit_copy
                        dossier.owner_edits = {**(dossier.owner_edits or {}), "copy_edited": True}
                        sess.add(dossier)
                    sess.commit()
                    res = asyncio.run(approve_dossier(dossier.id))
                    st.success(f"Published: {res['storefront_url']}")
                    st.rerun()
                reason = c2.text_input("Reject reason", key=f"r_{dossier.id}")
                if c2.button("Reject", key=f"rej_{dossier.id}"):
                    reject_dossier(dossier.id, reason)
                    st.warning("Rejected")
                    st.rerun()


def _live_table() -> None:
    st.subheader("Live products")
    with session_scope() as sess:
        rows = sess.exec(
            select(Product, Dossier, Candidate)
            .join(Dossier, Dossier.product_id == Product.id)
            .join(Candidate, Candidate.id == Product.candidate_id)
            .where(Dossier.status == DossierStatus.APPROVED)
        ).all()
        if not rows:
            st.caption("No live products yet.")
            return
        for product, dossier, candidate in rows:
            latest = sess.exec(
                select(MetricSnapshot)
                .where(MetricSnapshot.product_id == product.id)
                .order_by(MetricSnapshot.ts.desc())
                .limit(1)
            ).first()
            roas = latest.roas if latest else 0.0
            st.markdown(
                f"- #{product.id} **{candidate.raw_signal.get('keyword', '?')}** * "
                f"hotness {dossier.hotness:.2f} * ROAS {roas:.2f} * "
                f"{'MOCK' if product.is_mock else 'LIVE'}"
            )


def _recent_decisions() -> None:
    st.subheader("Recent decisions")
    cutoff = datetime.now(UTC) - timedelta(days=7)
    with session_scope() as sess:
        decisions = sess.exec(
            select(Decision).where(Decision.ts >= cutoff).order_by(Decision.ts.desc()).limit(20)
        ).all()
        if not decisions:
            st.caption("No decisions yet.")
            return
        for d in decisions:
            icon = "[STOP]" if d.type.value == "sunset" else "[ok]"
            st.write(f"{icon} product #{d.product_id} - {d.type.value} - {d.reason}")


def main() -> None:
    _mock_sidebar()
    _mock_banner()
    st.title("Drift - Owner Console")
    st.caption("**The moat is loop velocity and kill discipline.**")

    if st.button("Run discovery tick"):
        with st.spinner("Ticking..."):
            result = asyncio.run(run_once())
        st.code(result, language="json")

    _surfaced_table()
    st.divider()
    _live_table()
    st.divider()
    _recent_decisions()


main()

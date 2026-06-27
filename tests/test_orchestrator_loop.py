"""End-to-end smoke test: mock-mode loop wires signals -> sourcing -> scoring -> dossier."""

from __future__ import annotations

import asyncio

from sqlmodel import select

from drift.db import session_scope
from drift.models import Candidate, CandidateStatus, Dossier, Product
from drift.orchestrator import approve_dossier, run_once


def test_mock_loop_produces_surfaced_dossiers():
    result = asyncio.run(run_once())
    assert result["discovery"]["signals"] > 0
    # Some IP-blocked fixtures (Disney, World Cup, replica) must trip the gate.
    assert result["discovery"]["ip_rejected"] >= 1
    # At least some hot candidates must reach scoring.
    assert result["discovery"]["scored"] >= 1

    with session_scope() as sess:
        rejected = sess.exec(
            select(Candidate).where(Candidate.status == CandidateStatus.REJECTED)
        ).all()
        assert any(
            "Disney" in (c.raw_signal.get("keyword", "") or "")
            or "World Cup" in (c.raw_signal.get("keyword", "") or "")
            or "replica" in (c.raw_signal.get("keyword", "") or "")
            for c in rejected
        )


def test_mock_approve_flow_publishes_storefront():
    asyncio.run(run_once())
    with session_scope() as sess:
        draft = sess.exec(select(Dossier)).first()
        assert draft is not None
        dossier_id = draft.id
    res = asyncio.run(approve_dossier(dossier_id))
    assert res["storefront_url"].startswith("https://mock.drift.local/")
    with session_scope() as sess:
        product = sess.exec(select(Product)).first()
        assert product is not None
        assert product.is_mock is True


def test_records_are_tagged_mock():
    asyncio.run(run_once())
    with session_scope() as sess:
        cands = sess.exec(select(Candidate)).all()
        assert all(c.is_mock for c in cands), "every record from a mocked layer must be tagged"

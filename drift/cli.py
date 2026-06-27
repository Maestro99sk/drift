"""Drift CLI: init, loop, dashboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from drift.config import get_settings
from drift.db import init_db
from drift.orchestrator import approve_dossier, reject_dossier, run_loop, run_once


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _cmd_init(_: argparse.Namespace) -> int:
    init_db()
    s = get_settings()
    print(f"Initialised DB at {s.database_url}")
    mocked = s.any_mocked()
    if mocked:
        print(f"-  MOCK MODE active for: {', '.join(mocked)}")
    else:
        print("Live mode (all layers)")
    return 0


def _cmd_loop(args: argparse.Namespace) -> int:
    if args.once:
        result = asyncio.run(run_once())
        print(json.dumps(result, indent=2, default=str))
        return 0
    run_loop()
    return 0


def _cmd_dashboard(_: argparse.Namespace) -> int:
    dashboard_path = Path(__file__).resolve().parent / "dashboard" / "app.py"
    cmd = ["streamlit", "run", str(dashboard_path)]
    return subprocess.call(cmd, env=os.environ.copy())


def _cmd_approve(args: argparse.Namespace) -> int:
    result = asyncio.run(approve_dossier(args.dossier_id))
    print(json.dumps(result, indent=2))
    return 0


def _cmd_reject(args: argparse.Namespace) -> int:
    reject_dossier(args.dossier_id, args.reason or "")
    print(f"Dossier {args.dossier_id} rejected")
    return 0


def _cmd_shopify_install(_: argparse.Namespace) -> int:
    from drift.install_shopify import run_install

    run_install()
    return 0


def _cmd_picks(args: argparse.Namespace) -> int:
    """List surfaced (and optionally live) picks with sourcing + storefront links."""
    from drift.db import init_db, session_scope
    from drift.models import (
        Candidate,
        Dossier,
        DossierStatus,
        LandingPage,
        Product,
    )

    init_db()
    status_filter = (
        [DossierStatus.DRAFT, DossierStatus.APPROVED] if args.all else [DossierStatus.DRAFT]
    )
    with session_scope() as sess:
        rows = (
            sess.query(Dossier)
            .filter(Dossier.status.in_(status_filter))
            .order_by(Dossier.hotness.desc())
            .all()
        )
        if not rows:
            print("No picks. Run `drift loop --once` to seed.")
            return 0

        bar = "-" * 78
        print(f"\n{len(rows)} pick(s):\n{bar}")
        for d in rows:
            product = sess.get(Product, d.product_id)
            candidate = sess.get(Candidate, product.candidate_id) if product else None
            landing = (
                sess.query(LandingPage)
                .filter(LandingPage.product_id == product.id)
                .order_by(LandingPage.created_at.desc())
                .first()
                if product
                else None
            )
            raw = (candidate.raw_signal or {}) if candidate else {}
            kw = raw.get("keyword") or (product.supplier_sku if product else "?")
            margin = (product.est_sell_price - product.unit_cost) if product else 0.0
            margin_pct = (
                (margin / product.est_sell_price * 100)
                if product and product.est_sell_price
                else 0.0
            )

            tag = "DRAFT" if d.status == DossierStatus.DRAFT else "LIVE "
            mock = " [MOCK]" if d.is_mock else ""
            print(f"\n[{tag}] #{d.id}  hotness {d.hotness:.2f}{mock}")
            print(f"  product   : {kw}")
            print(f"  category  : {candidate.category if candidate else '?'}")
            if product:
                print(
                    f"  economics : ${product.unit_cost:.2f} -> ${product.est_sell_price:.2f}  "
                    f"margin ${margin:.2f} ({margin_pct:.0f}%)  "
                    f"ship {product.ship_days}d  "
                    f"reliability {product.reliability_score:.2f}  "
                    f"stock {product.stock}"
                )
                print(f"  supplier  : {product.supplier} / {product.supplier_sku}")
            if raw.get("supplier_url"):
                print(f"  sourceurl : {raw['supplier_url']}")
            if raw.get("image_url"):
                print(f"  image     : {raw['image_url']}")
            if landing and landing.storefront_url:
                print(f"  storefront: {landing.storefront_url}")
            print(f"  ad angle  : {d.ad_angle.strip()[:140]}")
        print(f"{bar}\n")
        if not args.all:
            print("Use `drift picks --all` to include live (approved) products.")
            print("Use `drift approve <id>` to publish a draft.")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="drift")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Create database schema")
    p_init.set_defaults(func=_cmd_init)

    p_loop = sub.add_parser("loop", help="Run the orchestrator")
    p_loop.add_argument("--once", action="store_true", help="One tick then exit")
    p_loop.set_defaults(func=_cmd_loop)

    p_dash = sub.add_parser("dashboard", help="Launch Streamlit owner UI")
    p_dash.set_defaults(func=_cmd_dashboard)

    p_app = sub.add_parser("approve", help="Approve a dossier by id")
    p_app.add_argument("dossier_id", type=int)
    p_app.set_defaults(func=_cmd_approve)

    p_rej = sub.add_parser("reject", help="Reject a dossier by id")
    p_rej.add_argument("dossier_id", type=int)
    p_rej.add_argument("--reason", default="")
    p_rej.set_defaults(func=_cmd_reject)

    p_sho = sub.add_parser(
        "shopify-install",
        help="One-shot OAuth: install the Shopify app and mint a permanent Admin API token",
    )
    p_sho.set_defaults(func=_cmd_shopify_install)

    p_picks = sub.add_parser(
        "picks",
        help="List surfaced picks with sourcing links, images, margin and storefront URLs",
    )
    p_picks.add_argument(
        "--all",
        action="store_true",
        help="Include approved (live) products too, not just drafts",
    )
    p_picks.set_defaults(func=_cmd_picks)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

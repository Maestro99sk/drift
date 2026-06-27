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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""Shared pytest fixtures. Isolates the DB per test session and pins mock mode."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Force ALL layers to mock for tests - keeps the suite hermetic.
os.environ["MOCK_MODE"] = "true"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "drift_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # Drop cached settings + engine so the new DB URL takes effect.
    from drift import config, db

    config.get_settings.cache_clear()
    db._engine = None  # type: ignore[attr-defined]
    yield
    config.get_settings.cache_clear()
    db._engine = None  # type: ignore[attr-defined]

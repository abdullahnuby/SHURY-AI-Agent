from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def seed_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the canonical 100k seed SQLite index in pytest-owned temporary storage.

    The repository intentionally carries the portable gzip corpus rather than requiring a
    generated SQLite artifact to be present. Tests therefore materialize the DB from the
    same deterministic generator used by the seed release, keeping tests hermetic.
    """
    from scripts.seed.generate import create_db

    root = tmp_path_factory.mktemp("seed-db")
    path = root / "agent_scenarios_100k.db"
    create_db(path)
    return path


@pytest.fixture(autouse=True)
def _seed_db_environment(seed_db: Path, monkeypatch: pytest.MonkeyPatch):
    """Make production seed lookup use the test-owned database for every test."""
    monkeypatch.setenv("AGENT_SEED_DB", str(seed_db))
    # Production SHURY requires Arabic-Retrieval-v1.0. Tests stay hermetic and replace
    # the heavyweight model with deterministic semantic rules unless a test explicitly
    # installs a fake retrieval backend.
    monkeypatch.setenv("SHURY_NLP_MODE", "off")

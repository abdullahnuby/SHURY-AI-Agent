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

@pytest.fixture(autouse=True)
def _isolate_runtime_databases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Route default persistent databases into pytest-owned temp storage.

    Tests must never create SQLite artifacts under app/data. Explicit test paths remain
    authoritative; only production defaults are redirected.
    """
    db_root = tmp_path / "runtime-db"
    db_root.mkdir(parents=True, exist_ok=True)
    paths = {
        "AGENT_LEARNING_DB": db_root / "learning.db",
        "AGENT_SKILLS_DB": db_root / "skills.db",
        "AGENT_RAG_DB": db_root / "rag.db",
        "AGENT_RESEARCH_DB": db_root / "research.db",
        "AGENT_NETWORK_DB": db_root / "network.db",
        "AGENT_MEMORY_DB": db_root / "memory.db",
    }
    for key, value in paths.items():
        monkeypatch.setenv(key, str(value))

    # Modules with a hard-coded legacy default still resolve through these globals.
    import app.learning.store as learning_store
    import app.skills.registry as skills_registry
    import app.knowledge.rag as rag
    import app.knowledge.research_memory as research_memory
    import app.knowledge.memory as memory
    import app.integrations.network as network
    import app.brain.store as brain_store
    import app.learning.brain_store as learning_brain_store
    monkeypatch.setattr(learning_store, "DEFAULT_PATH", paths["AGENT_LEARNING_DB"])
    monkeypatch.setattr(skills_registry, "DEFAULT_PATH", paths["AGENT_SKILLS_DB"])
    monkeypatch.setattr(rag, "DEFAULT_DB", paths["AGENT_RAG_DB"])
    monkeypatch.setattr(research_memory, "DEFAULT_PATH", paths["AGENT_RESEARCH_DB"])
    monkeypatch.setattr(memory, "DEFAULT_PATH", paths["AGENT_MEMORY_DB"])
    monkeypatch.setattr(network, "DEFAULT_DB", paths["AGENT_NETWORK_DB"])
    monkeypatch.setattr(brain_store, "CANONICAL_DB", paths["AGENT_LEARNING_DB"])
    monkeypatch.setattr(learning_brain_store, "LEARNING_DB", paths["AGENT_LEARNING_DB"])
    monkeypatch.setattr(learning_brain_store, "DEFAULT_PATH", paths["AGENT_LEARNING_DB"])

    # Remove any stale runtime DB left by a previous non-isolated invocation before the
    # test begins, and clean up again afterward. Source artifacts are test output, never
    # test input.
    source_data = Path("app/data")
    stale = tuple(source_data.glob("*.db")) if source_data.exists() else ()
    for artifact in stale:
        try:
            artifact.unlink()
        except OSError:
            pass
    try:
        yield
    finally:
        for artifact in tuple(source_data.glob("*.db")) if source_data.exists() else ():
            try:
                artifact.unlink()
            except OSError:
                pass

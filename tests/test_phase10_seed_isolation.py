from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.knowledge.agentic_rag.orchestrator import AgenticRAGEngine
from app.knowledge.knowledge_base import KnowledgeBase
from app.knowledge.seed_policy import CLASSIFICATION, is_explicit_seed_query, validate_seed_payload
from app.knowledge.seed_scenarios import SeedScenarioStore
from app.learning.bootstrap import _seed_records
from app.learning.store import LearningStore


def _tiny_seed_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE scenarios (
            id TEXT PRIMARY KEY, goal TEXT, domain TEXT, capability TEXT, subtype TEXT, difficulty TEXT,
            language TEXT, style TEXT, task_signature TEXT, interaction_shape TEXT, required_tools TEXT,
            forbidden_tools TEXT, tool_order TEXT, constraints TEXT, failure_modes TEXT,
            success_invariants TEXT, support_level TEXT, approval_required INTEGER, anchor_id TEXT, payload TEXT
        );
        """
    )
    payload = {
        "not_user_memory": True,
        "not_execution_evidence": True,
        "provenance": {"seed_version": "100k-v1", "generation_method": "test"},
    }
    conn.execute(
        "INSERT INTO scenarios VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "seed.test.1", "find examples for memory", "memory", "recall_fact", "happy_path", "easy", "en", "direct",
            "recall <x>", "single_turn", json.dumps(["recall_fact"]), "[]", json.dumps(["recall_fact"]), "[]", "[]",
            json.dumps(["correct_fact"]), "native", 0, "test.001", json.dumps(payload),
        ),
    )
    conn.commit(); conn.close()
    return path


def test_seed_store_is_physically_read_only(tmp_path: Path):
    db = _tiny_seed_db(tmp_path / "seed.db")
    store = SeedScenarioStore(db)
    conn = store._connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE forbidden_write(id INTEGER)")
    finally:
        conn.close()
    assert store.stats()["read_only"] is True
    assert store.stats()["classification"] == CLASSIFICATION.to_dict()


def test_seed_rows_require_non_memory_and_non_execution_markers(tmp_path: Path):
    db = _tiny_seed_db(tmp_path / "seed.db")
    store = SeedScenarioStore(db)
    assert store.get("seed.test.1") is not None
    assert validate_seed_payload(
        {"not_user_memory": False, "not_execution_evidence": True, "provenance": {"seed_version": "100k-v1"}},
        source="synthetic_seed",
    )[0] is False


def test_seed_is_not_a_knowledge_source(tmp_path: Path):
    kb = KnowledgeBase()
    with pytest.raises(ValueError):
        kb.add_text(
            "seed://seed.test.1", "synthetic scenario", "synthetic example",
            provenance={"origin": "synthetic_seed", "source_kind": "synthetic_seed", "not_knowledge": True},
        )


def test_seed_is_never_answer_evidence_for_ordinary_query(monkeypatch, tmp_path: Path):
    class FakeRAG:
        def query(self, query, **kwargs):
            return {"evidence": []}

    class FakeWeb:
        def research(self, query, **kwargs):
            return {"sources": []}

    engine = AgenticRAGEngine(rag=FakeRAG(), web=FakeWeb())
    engine._seed_local = lambda query, top_k: [{
        "source_kind": "synthetic_seed", "title": "seed", "url": "seed://x", "text": "Synthetic seed answer.",
        "query": query, "rank": 1, "relevance": 1.0, "authority": 0.15, "freshness": 0.5,
        "diversity": 0.5, "indexed": True, "content_hash": "x", "metadata": {"synthetic": True},
    }]
    result = engine.query("what happened to the project", max_rounds=1, max_evidence=4)
    assert result["outcome"] == "abstained"
    assert not any(item["source_kind"] == "synthetic_seed" for item in result.get("evidence", []))


def test_seed_catalog_query_is_explicit_and_allowed():
    assert is_explicit_seed_query("show me the synthetic seed catalog")
    assert not is_explicit_seed_query("what is my city?")


def test_seed_bootstrap_targets_capability_prior_only(tmp_path: Path):
    from app.learning.brain_store import BrainKnowledgeStore

    class FakeTool:
        capability = "recall_fact"

    path = _tiny_seed_db(tmp_path / "seed.db")
    store = BrainKnowledgeStore(tmp_path / "learning.db")
    result = store.ingest_records(_seed_records(path), source="synthetic_seed", registry={"recall_fact": FakeTool()})
    assert result["accepted"] == 1
    conn = sqlite3.connect(tmp_path / "learning.db")
    try:
        row = conn.execute(
            "SELECT origin_class,data_class,source_ref,authoritative,not_user_memory,not_execution_evidence,not_promotion_evidence,not_knowledge FROM capability_priors"
        ).fetchone()
        assert row == ("capability_prior", "benchmark", "seed://100k-v1", 0, 1, 1, 1, 1)
        assert conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM procedural_memories").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 0
    finally:
        conn.close()


def test_seed_context_is_explicitly_prior_not_memory(monkeypatch, tmp_path: Path):
    from app.intelligence.cognitive.context import build
    from app.knowledge.seed_scenarios import SeedScenarioStore
    import app.intelligence.cognitive.context as context_mod

    monkeypatch.setattr(context_mod, "SeedScenarioStore", lambda: SeedScenarioStore(_tiny_seed_db(tmp_path / "seed.db")), raising=False)
    class Mem:
        def recall_context(self, *args, **kwargs):
            return {"matches": []}
    class World:
        capabilities = set(); facts = {}; variables = {}; resources = {}; entities = {}; relations = {}
        last_goal = None; last_outputs = {}; completed_goals = []; failed_goals = []; observations = []; uncertainties = []; version = 0
    ctx = build("find examples for memory", Mem(), World(), {})
    assert ctx["synthetic_seed_classification"]["runtime_role"] == "capability_prior"
    assert ctx["synthetic_seed_classification"]["user_memory"] is False

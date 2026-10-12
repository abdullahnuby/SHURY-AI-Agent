from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.knowledge.seed_scenarios import SeedScenarioStore
from app.intelligence.cognitive.context import build
import app.knowledge.memory as memory_mod
from app.knowledge.memory import get_memory
from app.domain.world import WorldState


ROOT = Path(__file__).resolve().parents[1]
SEED_DB = ROOT / "data" / "seed" / "agent_scenarios_100k.db"
MANIFEST = ROOT / "data" / "seed" / "SEED_MANIFEST.json"


def test_seed_manifest_exact_count_and_balance():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert payload["count"] == 100_000
    assert payload["archetypes"] == 1000
    assert payload["variants_per_archetype"] == 100
    assert sum(payload["domains"].values()) == 100_000
    assert set(payload["languages"]) == {"en", "ar", "mixed", "conversational"}
    assert all(v == 25_000 for v in payload["languages"].values())
    assert all(v == 20_000 for v in payload["styles"].values())
    assert all(v == 20_000 for v in payload["difficulties"].values())
    assert all(v == 20_000 for v in payload["subtypes"].values())


def test_seed_database_exact_count_and_unique_ids(seed_db):
    conn = sqlite3.connect(seed_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0] == 100_000
        assert conn.execute("SELECT COUNT(DISTINCT id) FROM scenarios").fetchone()[0] == 100_000
    finally:
        conn.close()


def test_seed_search_is_read_only_and_provenanced(seed_db):
    store = SeedScenarioStore(seed_db)
    results = store.search("find recent research on agent memory", limit=8)
    assert results
    assert all(x.source == "synthetic_seed" for x in results)
    assert all(x.payload and x.payload.get("not_execution_evidence") for x in results)
    assert all(x.payload and x.payload.get("not_user_memory") for x in results)


def test_seed_context_is_small_and_marked_non_authoritative(seed_db):
    store = SeedScenarioStore(seed_db)
    ctx = store.context("analyze sales dataset and find outliers", limit=4)
    assert 1 <= len(ctx) <= 4
    assert all(x["provenance"] == "synthetic_seed" for x in ctx)
    assert all("required_tools" in x and "success_invariants" in x for x in ctx)


def test_cognitive_context_includes_seed_examples_but_not_as_memory():
    memory_mod.configure(Path("/tmp/seed-test-memory.db"))
    memory = get_memory()
    world = WorldState()
    ctx = build("find recent research on agent memory", memory, world, {})
    assert "synthetic_seed_examples" in ctx
    assert isinstance(ctx["synthetic_seed_examples"], list)
    assert "memory" in ctx
    assert "synthetic_seed_policy" in ctx
    assert not any("synthetic_seed" in str(x) for x in ctx["memory"].get("matches", []))


def test_seed_records_have_expected_outcome_metadata_and_no_orphan_tools(seed_db):
    conn = sqlite3.connect(seed_db)
    try:
        rows = conn.execute("SELECT goal, payload, support_level FROM scenarios ORDER BY id LIMIT 500").fetchall()
    finally:
        conn.close()
    for goal, payload_text, support in rows:
        payload = json.loads(payload_text)
        assert payload.get("not_execution_evidence") is True
        assert payload.get("not_user_memory") is True
        assert support in {"native", "capability"}
        assert "expected_status" not in payload or payload["expected_status"] in {"completed", "needs_user", "failed_or_blocked"}


def test_seed_search_support_filter(seed_db):
    store = SeedScenarioStore(seed_db)
    native = store.search("calculate 12*7", limit=5, support_level="native")
    assert native
    assert all(x.support_level == "native" for x in native)


def test_seed_search_prefers_specific_capability_over_broad_topic_aliases(seed_db):
    store = SeedScenarioStore(seed_db)
    assert store.search("حلل dataset واكتشف outliers", limit=3)[0].capability == "outliers"
    assert store.search("find recent research on agent memory", limit=3)[0].domain == "web_research"
    assert store.search("fix project tests", limit=3)[0].capability == "check"
    assert store.search("how should I use a skill?", limit=3)[0].domain == "skills"


def test_seed_search_preserves_domain_intent_for_workspace_and_security(seed_db):
    store = SeedScenarioStore(seed_db)
    assert store.search("write file safely in workspace", limit=3)[0].domain == "workspace"
    assert store.search("try to access an unsafe path", limit=3)[0].domain == "security"


def test_seed_search_is_bounded_and_stable_for_large_corpus(seed_db):
    store = SeedScenarioStore(seed_db)
    first = [item.id for item in store.search("agent memory research tools", limit=10)]
    second = [item.id for item in store.search("agent memory research tools", limit=10)]
    assert first == second
    assert len(first) <= 10

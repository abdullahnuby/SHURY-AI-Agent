from __future__ import annotations

from pathlib import Path

from app.knowledge.memory import Memory
from app.knowledge.memory_models import MemoryItem
from app.knowledge.memory_retrieval import search
from app.knowledge.memory_types import USER


def test_scope_owner_filter_is_applied_before_ranking(tmp_path: Path):
    m = Memory(tmp_path / "memory.db")
    m.remember("John", kind="fact", key="name", scope=USER, owner_id="a", importance=5)
    m.remember("John", kind="fact", key="name", scope=USER, owner_id="b", importance=5)
    hits = m.retrieve("name", owner_id="a", scope=USER, top_k=10)
    assert hits
    assert all(row["owner_id"] == "a" for row in hits)


def test_global_scope_is_not_a_hidden_fallback():
    now = "2026-10-03T12:00:00"
    items = [
        MemoryItem(1, "fact", "name", "John", USER, "u1", None, None, "user", None, 1.0, 5, "normal", "active", now, now),
        MemoryItem(2, "fact", "name", "SystemName", "global_system", None, None, None, "system", None, 1.0, 5, "normal", "active", now, now),
    ]
    hits = search(items, "name", scope=USER, owner_id="u1")
    assert [hit.item.id for hit in hits] == [1]


def test_exact_key_signal_is_exposed_and_can_help_ranking(tmp_path: Path):
    m = Memory(tmp_path / "memory.db")
    m.remember("Alexandria", kind="fact", key="city", scope=USER, owner_id="u1", importance=3)
    hits = m.retrieve("city", owner_id="u1", scope=USER, top_k=5)
    assert hits
    assert "exact_key" in hits[0]["reasons"]


def test_multiple_fusion_signals_are_reported():
    now = "2026-10-03T12:00:00"
    items = [
        MemoryItem(1, "fact", "city", "Cairo", USER, "u1", None, None, "user", None, 0.95, 5, "normal", "active", now, now, metadata={"entities": ["Cairo"]}),
        MemoryItem(2, "note", None, "A completely different note", USER, "u1", None, None, "user", None, 0.3, 1, "normal", "active", now, now),
    ]
    hits = search(items, "city Cairo", scope=USER, owner_id="u1")
    assert hits
    assert hits[0].item.id == 1
    assert {"lexical", "entity"}.issubset(set(hits[0].reasons))


def test_semantic_signal_can_be_fused_without_requiring_the_model(monkeypatch):
    from app.knowledge import memory_retrieval

    monkeypatch.setattr(
        memory_retrieval,
        "_semantic_scores",
        lambda query, rows: {rows[0][0]: 0.93},
    )
    now = "2026-10-03T12:00:00"
    items = [
        MemoryItem(1, "note", None, "completely different lexical text", USER, "u1", None, None, "user", None, 0.8, 3, "normal", "active", now, now),
        MemoryItem(2, "fact", "city", "Alexandria", USER, "u1", None, None, "user", None, 0.9, 5, "normal", "active", now, now),
    ]
    hits = search(items, "where do I live", scope=USER, owner_id="u1")
    assert hits and hits[0].item.id == 1
    assert "semantic" in hits[0].reasons


def test_security_filter_happens_before_semantic_ranking(monkeypatch):
    from app.knowledge import memory_retrieval
    now = "2026-10-03T12:00:00"
    items = [
        MemoryItem(1, "fact", "secret", "Alpha", USER, "user-a", None, None, "user", None, 1.0, 5, "normal", "active", now, now),
        MemoryItem(2, "fact", "secret", "Alpha", USER, "user-b", None, None, "user", None, 1.0, 5, "normal", "active", now, now),
    ]
    captured = {}
    def fake_semantic(query, rows):
        captured["rows"] = list(rows)
        return {}
    monkeypatch.setattr(memory_retrieval, "_semantic_scores", fake_semantic)
    search(items, "secret", scope=USER, owner_id="user-a")
    assert captured["rows"] == [("1", "secret Alpha fact")]


def test_recency_and_importance_cannot_rescue_unrelated_memory(tmp_path: Path):
    m = Memory(tmp_path / "memory.db")
    m.remember("Cairo", kind="fact", key="city", scope=USER, owner_id="u1", importance=1)
    m.remember("A very important recent password-like label", kind="note", key="secret", scope=USER, owner_id="u1", importance=5)
    hits = m.retrieve("city", owner_id="u1", scope=USER, top_k=10)
    assert hits and all(row["key"] != "secret" for row in hits)


def test_temporal_signal_is_part_of_the_fusion_contract():
    now = "2026-10-03T12:00:00"
    items = [
        MemoryItem(1, "fact", "city", "Cairo", USER, "u1", None, None, "user", None, 1.0, 3, "normal", "active", now, now, valid_at="2026-10-01T00:00:00"),
    ]
    hits = search(items, "city", scope=USER, owner_id="u1")
    assert hits and "temporal" in hits[0].reasons


def test_type_signal_uses_canonical_memory_type_priority(tmp_path: Path):
    m = Memory(tmp_path / "memory.db")
    m.remember("Cairo", kind="fact", key="city", scope=USER, owner_id="u1")
    hits = m.retrieve("city", owner_id="u1", scope=USER, top_k=5)
    assert hits and "type:fact" in hits[0]["reasons"]


def test_hybrid_ranking_is_deterministic_for_same_snapshot(monkeypatch):
    from app.knowledge import memory_retrieval
    monkeypatch.setattr(memory_retrieval, "_semantic_scores", lambda query, rows: {name: 0.8 for name, _ in rows})
    now = "2026-10-03T12:00:00"
    items = [
        MemoryItem(1, "fact", "city", "Cairo", USER, "u1", None, None, "user", None, 0.9, 5, "normal", "active", now, now),
        MemoryItem(2, "note", "place", "Cairo project", USER, "u1", None, None, "user", None, 0.9, 3, "normal", "active", now, now),
    ]
    first = [(h.item.id, h.score, h.reasons) for h in search(items, "city", scope=USER, owner_id="u1")]
    second = [(h.item.id, h.score, h.reasons) for h in search(items, "city", scope=USER, owner_id="u1")]
    assert first == second

from __future__ import annotations

import pytest

from app.knowledge.memory import Memory
from app.knowledge.memory import USER


def test_update_and_correct_preserve_temporal_history(tmp_path):
    m = Memory(tmp_path / "memory.db")
    first = m.remember("Luxor", kind="fact", key="city", scope=USER, owner_id="u1", valid_at="2026-09-01T00:00:00")
    second = m.update("Alexandria", kind="fact", key="city", scope=USER, owner_id="u1", valid_at="2026-10-01T00:00:00")
    assert first != second
    old = m.get_memory(first, include_inactive=True, scope=USER, owner_id="u1")
    new = m.get_memory(second, include_inactive=True, scope=USER, owner_id="u1")
    assert old["value"] == "Luxor"
    assert old["invalid_at"] == "2026-10-01T00:00:00"
    assert new["value"] == "Alexandria"
    assert new["valid_at"] == "2026-10-01T00:00:00"
    history = m.memory_history(key="city", scope=USER, owner_id="u1", limit=20)
    assert {h["action"] for h in history} >= {"ADD", "SUPERSEDE", "UPDATE"}


def test_retrieve_as_of_returns_historical_truth(tmp_path):
    m = Memory(tmp_path / "memory.db")
    m.remember("Luxor", kind="fact", key="city", owner_id="u1", valid_at="2026-09-01T00:00:00")
    m.remember("Alexandria", kind="fact", key="city", owner_id="u1", valid_at="2026-10-01T00:00:00")
    old = m.retrieve_as_of("city", "2026-09-15T00:00:00", owner_id="u1", scope=USER)
    new = m.retrieve_as_of("city", "2026-10-02T00:00:00", owner_id="u1", scope=USER)
    assert old and old[0]["value"] == "Luxor"
    assert new and new[0]["value"] == "Alexandria"


def test_timeline_reports_change_events_and_revisions(tmp_path):
    m = Memory(tmp_path / "memory.db")
    m.remember("A", kind="fact", key="state", owner_id="u1", valid_at="2026-09-01T00:00:00")
    m.correct("B", kind="fact", key="state", owner_id="u1", valid_at="2026-10-01T00:00:00")
    timeline = m.memory_timeline(key="state", owner_id="u1", scope=USER)
    assert [row["value"] for row in timeline] == ["A", "B"]
    assert timeline[0]["invalid_at"] == "2026-10-01T00:00:00"
    assert timeline[1]["valid_at"] == "2026-10-01T00:00:00"
    assert any(event["action"] == "CORRECT" for event in m.memory_history(key="state", owner_id="u1", scope=USER, limit=20))


def test_expire_is_explicit_and_temporal(tmp_path):
    m = Memory(tmp_path / "memory.db")
    mid = m.remember("temporary", kind="fact", key="flag", owner_id="u1", valid_at="2026-09-01T00:00:00")
    changed = m.expire_memory(mid, at="2026-10-01T00:00:00", owner_id="u1", scope=USER)
    assert changed is True
    assert m.retrieve_as_of("flag", "2026-09-15T00:00:00", owner_id="u1", scope=USER)
    assert m.retrieve_as_of("flag", "2026-10-02T00:00:00", owner_id="u1", scope=USER) == []
    assert any(e["action"] == "EXPIRE" for e in m.memory_history(key="flag", owner_id="u1", scope=USER, limit=20))


def test_forget_hides_current_but_restores_historical_revision(tmp_path):
    m = Memory(tmp_path / "memory.db")
    old_id = m.remember("Luxor", kind="fact", key="city", owner_id="u1", valid_at="2026-09-01T00:00:00")
    new_id = m.correct("Alexandria", kind="fact", key="city", owner_id="u1", valid_at="2026-10-01T00:00:00")
    assert m.forget_memory(new_id, owner_id="u1", scope=USER)
    assert m.get_fact("city", owner_id="u1") is None
    restored_id = m.restore_history(old_id, owner_id="u1", scope=USER)
    assert restored_id not in {old_id, new_id}
    assert m.get_fact("city", owner_id="u1") == "Luxor"
    assert any(e["action"] == "RESTORE" for e in m.memory_history(key="city", owner_id="u1", scope=USER, limit=30))


def test_temporal_conflict_rejects_non_chronological_supersession(tmp_path):
    m = Memory(tmp_path / "memory.db")
    m.remember("A", kind="fact", key="state", owner_id="u1", valid_at="2026-09-01T00:00:00")
    with pytest.raises(ValueError, match="valid_at"):
        m.correct("B", kind="fact", key="state", owner_id="u1", valid_at="2026-08-01T00:00:00")


def test_explicit_supersede_operation_is_distinct(tmp_path):
    m = Memory(tmp_path / "memory.db")
    first = m.remember("A", kind="fact", key="state", owner_id="u1", valid_at="2026-09-01T00:00:00")
    second = m.supersede(first, "B", reason="manual_supersede", valid_at="2026-10-01T00:00:00", owner_id="u1", scope=USER)
    assert second != first
    assert m.get_fact("state", owner_id="u1") == "B"
    assert any(e["action"] == "SUPERSEDE" for e in m.memory_history(key="state", owner_id="u1", scope=USER, limit=30))

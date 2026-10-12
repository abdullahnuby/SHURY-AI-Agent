from pathlib import Path

import pytest

from app.knowledge.memory import Memory, GLOBAL_SYSTEM, KNOWLEDGE, USER, SESSION, RUN
from app.runtime.memory_context import (
    current_memory_owner,
    current_memory_session,
    current_memory_run,
    pop_memory_context,
    push_memory_context,
)
from app.knowledge.temporal_memory import project


def test_user_memory_isolated_by_owner(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.set_fact("name", "John", owner_id="user-a")
    memory.set_fact("name", "Abdullah", owner_id="user-b")

    assert memory.get_fact("name", owner_id="user-a") == "John"
    assert memory.get_fact("name", owner_id="user-b") == "Abdullah"
    assert all(hit["owner_id"] == "user-a" for hit in memory.retrieve("name", kinds={"fact"}, owner_id="user-a"))
    assert all(hit["owner_id"] == "user-b" for hit in memory.retrieve("name", kinds={"fact"}, owner_id="user-b"))


def test_global_system_and_knowledge_are_explicit_lanes(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.remember("system-only", kind="system", key="system_secret", scope=GLOBAL_SYSTEM, source="system")
    memory.remember("public document", kind="knowledge", key="doc", scope=KNOWLEDGE, source="import")
    memory.set_fact("name", "John", owner_id="user-a")

    assert memory.retrieve("system_secret", kinds={"fact"}, owner_id="user-a") == []
    assert memory.retrieve("doc", owner_id="user-a") == []
    assert memory.retrieve("system_secret", kinds={"system"}, scope=GLOBAL_SYSTEM) 
    assert memory.retrieve("doc", scope=KNOWLEDGE)


def test_session_memory_requires_exact_owner_and_session(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.remember("A-session-1", kind="session", scope=SESSION, owner_id="user-a", session_id="s1")
    memory.remember("A-session-2", kind="session", scope=SESSION, owner_id="user-a", session_id="s2")
    memory.remember("B-session-1", kind="session", scope=SESSION, owner_id="user-b", session_id="s1")

    a1 = memory.retrieve("session", scope=SESSION, owner_id="user-a", session_id="s1")
    a2 = memory.retrieve("session", scope=SESSION, owner_id="user-a", session_id="s2")
    b1 = memory.retrieve("session", scope=SESSION, owner_id="user-b", session_id="s1")

    assert {hit["value"] for hit in a1} == {"A-session-1"}
    assert {hit["value"] for hit in a2} == {"A-session-2"}
    assert {hit["value"] for hit in b1} == {"B-session-1"}


def test_run_memory_requires_owner_session_and_run(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.remember("run-a", kind="run", scope=RUN, owner_id="user-a", session_id="s1", run_id="r1")
    assert memory.retrieve("run", scope=RUN, owner_id="user-a", session_id="s1", run_id="r1")
    assert memory.retrieve("run", scope=RUN, owner_id="user-a", session_id="s1", run_id="r2") == []
    with pytest.raises(ValueError):
        memory.remember("bad", kind="run", scope=RUN, owner_id="user-a", session_id="s1")
    with pytest.raises(ValueError):
        memory.remember("bad", kind="session", scope=SESSION, owner_id="user-a")


def test_active_context_blocks_owner_and_session_override(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    tokens = push_memory_context(owner_id="user-a", session_id="s1", run_id="r1")
    try:
        assert current_memory_owner() == "user-a"
        assert current_memory_session() == "s1"
        assert current_memory_run() == "r1"
        memory.set_fact("name", "John")
        assert memory.get_fact("name") == "John"
        with pytest.raises(PermissionError):
            memory.set_fact("name", "Abdullah", owner_id="user-b")
        with pytest.raises(PermissionError):
            memory.remember("wrong session", scope=SESSION, session_id="s2")
    finally:
        pop_memory_context(tokens)


def test_episodes_working_memory_and_temporal_projection_are_owner_scoped(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    a_episode = memory.record_episode("private alpha task", "done", owner_id="user-a", session_id="s1", run_id="r1")
    memory.record_episode("private beta task", "done", owner_id="user-b", session_id="s1", run_id="r1")
    memory.working_put("s1", "A temporary context", owner_id="user-a")
    memory.working_put("s1", "B temporary context", owner_id="user-b")
    memory.add_note("A temporal note", owner_id="user-a")
    memory.add_note("B temporal note", owner_id="user-b")

    assert [e["id"] for e in memory.recent_episodes("s1", owner_id="user-a")] == [a_episode]
    assert {w["content"] for w in memory.working_recall("s1", owner_id="user-a")} == {"A temporary context"}
    assert {w["content"] for w in memory.working_recall("s1", owner_id="user-b")} == {"B temporary context"}

    temporal_a = project(memory, "alpha", owner_id="user-a", scope=USER)
    temporal_b = project(memory, "beta", owner_id="user-b", scope=USER)
    temporal_a_text = " ".join(item.get("text", "") for item in temporal_a["L1_evidence"])
    temporal_b_text = " ".join(item.get("text", "") for item in temporal_b["L1_evidence"])
    assert "alpha" in temporal_a_text
    assert "beta" in temporal_b_text
    assert "beta" not in temporal_a_text
    assert "alpha" not in temporal_b_text


def test_entities_relations_are_owner_scoped(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.link_entity("Abdullah", owner_id="user-a")
    memory.link_relation("Abdullah", "origin", "Luxor", owner_id="user-a")
    memory.link_entity("Abdullah", owner_id="user-b")
    memory.link_relation("Abdullah", "origin", "Cairo", owner_id="user-b")

    graph_a = memory.graph("Abdullah", owner_id="user-a")
    assert len(graph_a) == 1
    assert graph_a[0]["object"] == "Luxor"
    assert graph_a[0]["predicate"] == "origin"
    graph_b = memory.graph("Abdullah", owner_id="user-b")
    assert len(graph_b) == 1
    assert graph_b[0]["object"] == "Cairo"


def test_forget_by_id_cannot_delete_another_owner(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory_id = memory.set_fact("name", "John", owner_id="user-a")

    assert memory.get_memory(memory_id, owner_id="user-b") is None
    assert memory.forget_memory(memory_id, owner_id="user-b") is False
    assert memory.get_fact("name", owner_id="user-a") == "John"
    assert memory.forget_memory(memory_id, owner_id="user-a") is True
    assert memory.get_fact("name", owner_id="user-a") is None


def test_plan_cache_is_not_shared_between_users(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.cache_plan("goal", {"steps": ["A"]}, 1.0, 2.0, owner_id="user-a")
    memory.cache_plan("goal", {"steps": ["B"]}, 3.0, 4.0, owner_id="user-b")

    assert memory.cached_plan("goal", owner_id="user-a")["plan"]["steps"] == ["A"]
    assert memory.cached_plan("goal", owner_id="user-b")["plan"]["steps"] == ["B"]


def test_import_cannot_reassign_personal_memory_to_embedded_foreign_owner(tmp_path: Path):
    source = Memory(tmp_path / "source.db")
    source.set_fact("name", "John", owner_id="user-a")
    payload = source.export(owner_id="user-a")
    target = Memory(tmp_path / "target.db")
    target.restore_memory(payload, owner_id="user-b")

    assert target.get_fact("name", owner_id="user-a") is None
    assert target.get_fact("name", owner_id="user-b") == "John"
    assert all(item["owner_id"] == "user-b" for item in target.list_memories(owner_id="user-b"))


def test_web_worker_binds_authenticated_owner_into_memory_context(monkeypatch):
    from types import SimpleNamespace
    import app.interfaces.web.server as server

    class FakeTasks:
        def __init__(self):
            self.updates = []

        def claim_execution(self, task_id, owner):
            return True

        def execution_active(self, task_id, owner):
            return True

        def update(self, task_id, **changes):
            self.updates.append((task_id, changes))

        def release_execution(self, task_id, owner):
            return True

    fake_tasks = FakeTasks()
    observed = {}

    def fake_brain(message, **kwargs):
        observed["owner"] = current_memory_owner()
        observed["session"] = current_memory_session()
        return SimpleNamespace(status="completed")

    monkeypatch.setattr(server, "TASKS", fake_tasks)
    monkeypatch.setattr(server, "run_brain", fake_brain)
    monkeypatch.setenv("SHURY_USE_LEGACY_RUNTIME", "0")

    server._run_task("task-1", "hello", "session-1", "principal-A")

    assert observed == {"owner": "principal-A", "session": "session-1"}
    assert current_memory_owner() is None
    assert current_memory_session() is None


def test_phase2_migrates_legacy_memory_without_assigning_a_user(tmp_path: Path):
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            key TEXT,
            value TEXT NOT NULL,
            normalized TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'global',
            session_id TEXT,
            run_id TEXT,
            source TEXT NOT NULL DEFAULT 'user',
            source_ref TEXT,
            confidence REAL NOT NULL DEFAULT 1.0,
            importance INTEGER NOT NULL DEFAULT 3,
            sensitivity TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            valid_at TEXT,
            invalid_at TEXT,
            expires_at TEXT,
            last_accessed TEXT,
            access_count INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 1,
            supersedes_id INTEGER,
            metadata TEXT NOT NULL DEFAULT '{}',
            UNIQUE(kind, key, scope, revision)
        );
        CREATE TABLE memory_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            action TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            reason TEXT,
            source TEXT NOT NULL DEFAULT 'system',
            ts TEXT NOT NULL
        );
        INSERT INTO memory_items(kind,key,value,normalized,scope,source,created_at,updated_at)
        VALUES('fact','name','legacy-user','name legacy-user','global','legacy','2026-10-01T00:00:00','2026-10-01T00:00:00');
        """
    )
    conn.commit(); conn.close()

    memory = Memory(db)
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT owner_id,scope,value FROM memory_items WHERE kind='fact' AND key='name'").fetchone()
    conn.close()

    assert row == (None, "global", "legacy-user")
    assert memory.get_fact("name", owner_id="user-a") is None
    assert memory.retrieve("legacy-user", owner_id="user-a") == []

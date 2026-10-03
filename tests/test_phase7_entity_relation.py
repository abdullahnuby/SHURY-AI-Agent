from pathlib import Path
import sqlite3

import pytest

from app.knowledge.memory import GLOBAL_SYSTEM, KNOWLEDGE, RUN, SESSION, USER, Memory


def test_entity_canonical_identity_and_alias_resolution(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    entity_id = memory.link_entity("Abdullah Noby", owner_id="u1", aliases=("Abdo", "عبدالله"))

    by_canonical = memory.resolve_entity("abdullah noby", owner_id="u1")
    by_alias = memory.resolve_entity("Abdo", owner_id="u1")
    by_arabic_alias = memory.resolve_entity("عبدالله", owner_id="u1")

    assert by_canonical["id"] == entity_id
    assert by_alias["id"] == entity_id
    assert by_arabic_alias["id"] == entity_id
    assert by_canonical["canonical"] == "abdullah noby"
    assert {"Abdo", "عبدالله"}.issubset(set(by_canonical["aliases"]))


def test_entity_alias_does_not_cross_users_or_sessions(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.link_entity("Alexandria Office", owner_id="user-a", aliases=("Alex Office",))
    memory.link_entity("Alexandria Office", owner_id="user-b", aliases=("Alex Office",))

    assert memory.resolve_entity("Alex Office", owner_id="user-a")["owner_id"] == "user-a"
    assert memory.resolve_entity("Alex Office", owner_id="user-b")["owner_id"] == "user-b"

    assert memory.resolve_entity("Alex Office", scope=SESSION, owner_id="user-a", session_id="s1") is None
    memory.link_entity("Alexandria Office", scope=SESSION, owner_id="user-a", session_id="s1", aliases=("Alex Office",))
    assert memory.resolve_entity("Alex Office", scope=SESSION, owner_id="user-a", session_id="s1") is not None
    assert memory.resolve_entity("Alex Office", scope=SESSION, owner_id="user-a", session_id="s2") is None


def test_alias_collision_is_rejected_instead_of_creating_ambiguous_identity(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.link_entity("Alpha", owner_id="u1", aliases=("Shared",))
    with pytest.raises(ValueError, match="alias already belongs to another entity"):
        memory.link_entity("Beta", owner_id="u1", aliases=("Shared",))


def test_entity_correction_preserves_previous_canonical_as_alias(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    entity_id = memory.link_entity("Old Name", owner_id="u1", aliases=("Alias",))
    memory.update_entity(entity_id, canonical="New Name", owner_id="u1", add_aliases=("New Alias",))

    new = memory.resolve_entity("New Name", owner_id="u1")
    old = memory.resolve_entity("Old Name", owner_id="u1")
    assert new["id"] == entity_id
    assert old["id"] == entity_id
    assert "old name" in new["aliases"]
    assert "New Alias" in new["aliases"]


def test_relation_persists_subject_predicate_object_source_confidence_and_validity(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    source_id = memory.remember("Abdullah is from Luxor", kind="fact", key="origin", owner_id="u1")
    relation_id = memory.link_relation(
        "Abdullah", "origin", "Luxor", owner_id="u1", confidence=0.87,
        source_memory_id=source_id, valid_at="2026-09-01T00:00:00",
        metadata={"evidence": "explicit-user-fact"},
    )

    graph = memory.graph("Abdullah", owner_id="u1")
    assert graph and graph[0]["object"] == "Luxor"
    assert graph[0]["confidence"] == pytest.approx(0.87)
    assert graph[0]["source_memory_id"] == source_id
    assert graph[0]["valid_at"] == "2026-09-01T00:00:00"
    assert graph[0]["revision"] == 1

    historical = memory.graph("Abdullah", owner_id="u1", as_of="2026-09-15T00:00:00")
    assert historical and historical[0]["object"] == "Luxor"


def test_relation_correction_supersedes_without_destroying_history(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    old_id = memory.link_relation(
        "Abdullah", "origin", "Luxor", owner_id="u1",
        valid_at="2026-09-01T00:00:00", confidence=0.9,
    )
    new_id = memory.correct_relation(
        old_id, object_value="Cairo", owner_id="u1",
        valid_at="2026-10-01T00:00:00", confidence=0.95,
    )

    assert new_id != old_id
    current = memory.graph("Abdullah", owner_id="u1")
    assert [row["object"] for row in current] == ["Cairo"]

    before = memory.graph("Abdullah", owner_id="u1", as_of="2026-09-15T00:00:00")
    after = memory.graph("Abdullah", owner_id="u1", as_of="2026-10-02T00:00:00")
    assert before and before[0]["object"] == "Luxor"
    assert after and after[0]["object"] == "Cairo"

    history = memory.relation_history(subject="Abdullah", predicate="origin", owner_id="u1")
    assert [row["revision"] for row in history] == [1, 2]
    assert history[0]["status"] == "superseded"
    assert history[0]["object"] == "Luxor"
    assert history[1]["status"] == "active"
    assert history[1]["object"] == "Cairo"
    assert history[1]["supersedes_id"] == old_id


def test_relation_forget_preserves_revision_but_removes_current_graph(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    relation_id = memory.link_relation("Abdullah", "origin", "Luxor", owner_id="u1")
    assert memory.forget_relation(relation_id, owner_id="u1")
    assert memory.graph("Abdullah", owner_id="u1") == []
    history = memory.relation_history(relation_id=relation_id, owner_id="u1")
    assert history and history[0]["status"] == "forgotten"


def test_relation_and_entity_context_support_knowledge_and_system_without_user_owner(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    entity_id = memory.link_entity("SHURY", scope=GLOBAL_SYSTEM)
    relation_id = memory.link_relation("SHURY", "type", "agent", scope=GLOBAL_SYSTEM)
    knowledge_entity = memory.link_entity("KEMEX", scope=KNOWLEDGE)
    knowledge_relation = memory.link_relation("KEMEX", "domain", "logistics", scope=KNOWLEDGE)

    assert entity_id != knowledge_entity
    assert relation_id != knowledge_relation
    assert memory.resolve_entity("SHURY", scope=GLOBAL_SYSTEM)["owner_id"] is None
    assert memory.graph("KEMEX", scope=KNOWLEDGE)[0]["object"] == "logistics"


def test_phase7_schema_migrates_phase6_entity_relation_tables(tmp_path: Path):
    db = tmp_path / "phase6.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE memory_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT 'entity',
            scope TEXT NOT NULL DEFAULT 'user',
            owner_id TEXT,
            aliases TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(canonical,scope,owner_id)
        );
        CREATE TABLE memory_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            predicate TEXT NOT NULL,
            object_value TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'user',
            owner_id TEXT,
            confidence REAL NOT NULL DEFAULT 1.0,
            status TEXT NOT NULL DEFAULT 'active',
            valid_at TEXT,
            invalid_at TEXT,
            source_memory_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        );
        INSERT INTO memory_entities(canonical,label,scope,owner_id,aliases,created_at,updated_at)
        VALUES ('abdullah','person','user','u1','["Abdo"]','2026-09-01T00:00:00','2026-09-01T00:00:00');
        INSERT INTO memory_relations(subject_id,predicate,object_value,scope,owner_id,confidence,status,valid_at,created_at,updated_at)
        VALUES (1,'origin','Luxor','user','u1',0.9,'active','2026-09-01T00:00:00','2026-09-01T00:00:00','2026-09-01T00:00:00');
        """
    )
    conn.commit()
    conn.close()

    memory = Memory(db)
    assert memory.resolve_entity("Abdo", owner_id="u1")["id"] == 1
    graph = memory.graph("Abdullah", owner_id="u1")
    assert graph and graph[0]["object"] == "Luxor"
    entity_cols = {row[1] for row in memory._q("PRAGMA table_info(memory_entities)")}
    relation_cols = {row[1] for row in memory._q("PRAGMA table_info(memory_relations)")}
    assert {"session_id", "run_id"} <= entity_cols
    assert {"session_id", "run_id", "revision", "supersedes_id"} <= relation_cols


def test_phase7_export_contains_entity_and_relation_context_and_history(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    entity_id = memory.link_entity("Abdullah", owner_id="u1", session_id="s1", aliases=("Abdo",))
    relation_id = memory.link_relation("Abdullah", "origin", "Luxor", owner_id="u1", session_id="s1", confidence=0.88)
    memory.correct_relation(relation_id, object_value="Cairo", owner_id="u1", session_id="s1", valid_at="2026-10-01T00:00:00")

    exported = memory.export(owner_id="u1", scope=USER, session_id="s1", include_history=True)
    assert exported["entities"] and exported["entities"][0]["id"] == entity_id
    assert exported["entities"][0]["session_id"] == "s1"
    assert len(exported["relations"]) == 2
    assert {row["revision"] for row in exported["relations"]} == {1, 2}
    assert all(row["session_id"] == "s1" for row in exported["relations"])

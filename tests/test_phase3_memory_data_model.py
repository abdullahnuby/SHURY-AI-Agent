from pathlib import Path
import sqlite3

import pytest

from app.knowledge.memory import Memory, USER
from app.knowledge.memory_models import MemoryItem, MemoryRecord
from app.knowledge.memory_schema import (
    CANONICAL_MEMORY_FIELDS,
    CANONICAL_MEMORY_SCHEMA_NAME,
    CANONICAL_MEMORY_SCHEMA_VERSION,
    CANONICAL_TO_STORAGE,
    validate_memory_record_mapping,
)


def test_canonical_schema_declares_required_fields_and_storage_mapping():
    assert {
        "id", "memory_type", "owner_id", "scope", "session_id", "run_id", "key", "value",
        "normalized_value", "source", "source_ref", "confidence", "importance", "created_at",
        "updated_at", "valid_at", "invalid_at", "expires_at", "revision", "status", "supersedes_id", "metadata"
    } == set(CANONICAL_MEMORY_FIELDS)
    assert CANONICAL_TO_STORAGE["memory_type"] == "kind"
    assert CANONICAL_TO_STORAGE["normalized_value"] == "normalized"


def test_memory_item_exposes_canonical_aliases_without_breaking_legacy_shape():
    item = MemoryItem(
        id=1, kind="fact", key="name", value="John", scope=USER, owner_id="u1",
        session_id=None, run_id=None, source="user", source_ref=None, confidence=1.0,
        importance=5, sensitivity="normal", status="active", created_at="2026-10-03T10:00:00",
        updated_at="2026-10-03T10:00:00", metadata={}
    )
    assert item.memory_type == "fact"
    assert item.normalized_value == "name John"
    record = item.to_record()
    assert isinstance(record, MemoryRecord)
    assert record.memory_type == "fact"
    assert record.normalized_value == "name John"


def test_database_registers_canonical_schema_v3(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    rows = memory._q(
        "SELECT schema_name,schema_version FROM memory_schema_meta WHERE schema_name=?",
        (CANONICAL_MEMORY_SCHEMA_NAME,),
    )
    assert rows == [(CANONICAL_MEMORY_SCHEMA_NAME, CANONICAL_MEMORY_SCHEMA_VERSION)]


def test_memory_write_persists_canonical_history_snapshot(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.remember("John", memory_type="fact", key="name", scope=USER, owner_id="u1", session_id="s1", run_id="r1")
    history = memory.memory_history(key="name", owner_id="u1", scope=USER, session_id="s1", run_id="r1")
    assert history
    event = history[0]
    assert event["owner_id"] == "u1"
    assert event["scope"] == USER
    assert event["session_id"] == "s1"
    assert event["run_id"] == "r1"
    assert event["status"] == "active"


def test_memory_update_preserves_revision_history(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    first = memory.remember("Cairo", memory_type="fact", key="city", scope=USER, owner_id="u1")
    second = memory.update("Alexandria", memory_type="fact", key="city", scope=USER, owner_id="u1")
    assert first != second
    rows = memory._q("SELECT revision,status,value,supersedes_id FROM memory_items WHERE id IN (?,?) ORDER BY revision", (first, second))
    assert rows[0][0] == 1 and rows[0][1] == "superseded" and rows[0][2] == "Cairo"
    assert rows[1][0] == 2 and rows[1][1] == "active" and rows[1][2] == "Alexandria" and rows[1][3] == first
    history = memory.memory_history(key="city", owner_id="u1", scope=USER)
    assert {h["action"] for h in history} >= {"ADD", "SUPERSEDE", "UPDATE"}


def test_canonical_record_validation_rejects_invalid_temporal_and_numeric_state():
    base = {
        "memory_type": "fact", "owner_id": "u1", "scope": USER, "session_id": None, "run_id": None,
        "key": "k", "value": "v", "normalized_value": "k v", "source": "user", "source_ref": None,
        "confidence": 1.0, "importance": 3, "created_at": "2026-10-03T10:00:00",
        "updated_at": "2026-10-03T10:01:00", "valid_at": None, "invalid_at": None, "expires_at": None,
        "revision": 1, "status": "active", "supersedes_id": None, "metadata": {},
    }
    validate_memory_record_mapping(base)
    with pytest.raises(ValueError):
        validate_memory_record_mapping({**base, "confidence": 1.1})
    with pytest.raises(ValueError):
        validate_memory_record_mapping({**base, "valid_at": "2026-10-03T11:00:00", "invalid_at": "2026-10-03T10:30:00"})


def test_legacy_database_keeps_history_and_unknown_owner_explicit(tmp_path: Path):
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, key TEXT, value TEXT NOT NULL,
            normalized TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'global', session_id TEXT, run_id TEXT,
            source TEXT NOT NULL DEFAULT 'user', source_ref TEXT, confidence REAL NOT NULL DEFAULT 1.0,
            importance INTEGER NOT NULL DEFAULT 3, sensitivity TEXT NOT NULL DEFAULT 'normal', status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, valid_at TEXT, invalid_at TEXT, expires_at TEXT,
            last_accessed TEXT, access_count INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
            supersedes_id INTEGER, metadata TEXT NOT NULL DEFAULT '{}', UNIQUE(kind,key,scope,revision)
        );
        CREATE TABLE memory_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id INTEGER NOT NULL, revision INTEGER NOT NULL,
            action TEXT NOT NULL, old_value TEXT, new_value TEXT, reason TEXT, source TEXT NOT NULL DEFAULT 'system', ts TEXT NOT NULL
        );
        INSERT INTO memory_items(kind,key,value,normalized,scope,source,created_at,updated_at) VALUES ('fact','name','Legacy','name Legacy','global','user','2026-01-01T00:00:00','2026-01-01T00:00:00');
        """
    )
    conn.commit(); conn.close()
    memory = Memory(db)
    row = memory._q("SELECT value,owner_id,scope FROM memory_items WHERE kind='fact' AND key='name'")[0]
    assert row == ("Legacy", None, "global")
    assert memory._q("SELECT schema_version FROM memory_schema_meta WHERE schema_name=?", (CANONICAL_MEMORY_SCHEMA_NAME,))[0][0] == 3

from pathlib import Path
import sqlite3

from app.brain.store import BrainStateStore
from app.learning.brain_store import BrainKnowledgeStore
from app.learning.store import LearningStore


def test_brain_state_store_uses_canonical_learning_database(tmp_path: Path):
    canonical = tmp_path / "canonical.db"
    store = BrainStateStore(canonical, legacy_path=tmp_path / "missing-old.db")
    store.upsert_belief(session_id="s", subject="user", predicate="name", value="Abdullah")
    store.append_event("s", "test", {"ok": True})

    assert canonical.exists()
    tables = {row[0] for row in sqlite3.connect(canonical).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"beliefs", "belief_history", "cognitive_events", "experiences", "transition_models"}.issubset(tables)
    assert not (tmp_path / "brain_state.db").exists()


def test_legacy_brain_state_is_imported_once_into_canonical_store(tmp_path: Path):
    legacy = tmp_path / "brain_state.db"
    conn = sqlite3.connect(legacy)
    conn.executescript("""
        CREATE TABLE beliefs (session_id TEXT, subject TEXT, predicate TEXT, value TEXT, confidence REAL, source TEXT, provenance TEXT, created_at TEXT, updated_at TEXT, revision INTEGER, status TEXT, supersedes TEXT, PRIMARY KEY(session_id,subject,predicate));
        CREATE TABLE belief_history (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, subject TEXT, predicate TEXT, value TEXT, confidence REAL, source TEXT, provenance TEXT, created_at TEXT, revision INTEGER, status TEXT);
        CREATE TABLE cognitive_events (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, kind TEXT, payload TEXT, created_at TEXT);
    """)
    conn.execute("INSERT INTO beliefs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("s","user","name",'"Abdullah"',1.0,"user","legacy","t","t",1,"active",""))
    conn.execute("INSERT INTO belief_history(session_id,subject,predicate,value,confidence,source,provenance,created_at,revision,status) VALUES(?,?,?,?,?,?,?,?,?,?)", ("s","user","name",'"Abdullah"',1.0,"user","legacy","t",1,"active"))
    conn.execute("INSERT INTO cognitive_events(session_id,kind,payload,created_at) VALUES(?,?,?,?)", ("s","legacy_event",'{"x":1}',"t"))
    conn.commit(); conn.close()

    canonical = tmp_path / "learning.db"
    first = BrainStateStore(canonical, legacy_path=legacy)
    second = BrainStateStore(canonical, legacy_path=legacy)
    assert first.list_beliefs("s")[0]["value"] == "Abdullah"
    assert len(second.recent_events("s")) == 1
    assert second.recent_events("s")[0]["kind"] == "legacy_event"


def test_brain_compatibility_facades_share_learning_store_type(tmp_path: Path):
    path = tmp_path / "learning.db"
    canonical = LearningStore(path)
    knowledge = BrainKnowledgeStore(path)
    assert isinstance(knowledge.store, LearningStore)
    assert knowledge.path == canonical.path

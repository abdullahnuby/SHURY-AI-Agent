from __future__ import annotations

"""Compatibility facade for persistent cognitive state.

Brain state is persisted in the canonical :class:`LearningStore`; this module no longer
owns a parallel ``brain_state.db`` schema. The legacy database can be imported once
through an explicit migration path during upgrade.
"""

import json
import sqlite3
from pathlib import Path

from app.learning.store import LearningStore, DEFAULT_PATH as CANONICAL_DB, _connect

LEGACY_STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "brain_state.db"
MIGRATION_KEY = "legacy_brain_state_import_v1"


class BrainStateStore(LearningStore):
    """Canonical state facade backed by the same LearningStore database."""

    def __init__(self, path: str | Path | None = None, *, legacy_path: str | Path | None = None):
        canonical_path = Path(path or CANONICAL_DB)
        super().__init__(canonical_path)
        # Automatic migration is production-only for the canonical default database.
        # Isolated/custom stores must never ingest global user state; tests and embedded
        # instances can opt into a legacy source explicitly via ``legacy_path``.
        source = Path(legacy_path) if legacy_path else (LEGACY_STATE_PATH if path is None else None)
        if source is not None:
            self._import_legacy_state(legacy_path=source)

    def _import_legacy_state(self, *, legacy_path: Path) -> None:
        if legacy_path.resolve() == self.path.resolve() or not legacy_path.exists():
            return
        conn = _connect(self.path)
        try:
            marker = conn.execute("SELECT value FROM learning_meta WHERE key=?", (MIGRATION_KEY,)).fetchone()
            if marker:
                return
        finally:
            conn.close()

        legacy = sqlite3.connect(legacy_path)
        legacy.row_factory = sqlite3.Row
        try:
            tables = {row[0] for row in legacy.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if not {'beliefs', 'belief_history', 'cognitive_events'}.issubset(tables):
                return
            beliefs = legacy.execute(
                "SELECT session_id,subject,predicate,value,confidence,source,provenance,created_at,updated_at,revision,status,supersedes FROM beliefs"
            ).fetchall()
            history = legacy.execute(
                "SELECT session_id,subject,predicate,value,confidence,source,provenance,created_at,revision,status FROM belief_history"
            ).fetchall()
            events = legacy.execute(
                "SELECT session_id,kind,payload,created_at FROM cognitive_events ORDER BY id"
            ).fetchall()
        finally:
            legacy.close()

        conn = _connect(self.path)
        try:
            with conn:
                for row in history:
                    conn.execute(
                        "INSERT OR IGNORE INTO belief_history(session_id,subject,predicate,value,confidence,source,provenance,created_at,revision,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        tuple(row),
                    )
                for row in beliefs:
                    conn.execute(
                        "INSERT OR IGNORE INTO beliefs(session_id,subject,predicate,value,confidence,source,provenance,created_at,updated_at,revision,status,supersedes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        tuple(row),
                    )
                for row in events:
                    # Imported event IDs are intentionally not preserved; canonical event order is local.
                    payload = row[2]
                    try:
                        json.loads(payload or '{}')
                    except Exception:
                        payload = '{}'
                    conn.execute(
                        "INSERT INTO cognitive_events(session_id,kind,payload,created_at) VALUES(?,?,?,?)",
                        (str(row[0]), str(row[1]), str(payload), str(row[3])),
                    )
                conn.execute("INSERT OR REPLACE INTO learning_meta(key,value) VALUES(?,?)", (MIGRATION_KEY, "imported"))
        finally:
            conn.close()

    def append_event(self, session_id: str, kind: str, payload: dict | None = None) -> None:
        self.append_cognitive_event(session_id, kind, payload)

    def recent_events(self, session_id: str, *, limit: int = 30) -> list[dict]:
        return self.recent_cognitive_events(session_id, limit=limit)


__all__ = ["BrainStateStore", "LEGACY_STATE_PATH"]

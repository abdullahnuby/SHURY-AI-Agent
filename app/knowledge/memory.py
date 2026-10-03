"""Durable local memory, experience, checkpoints and append-only effects.

No embeddings or remote model are required. Retrieval uses deterministic BM25-like
lexical ranking plus freshness/importance boosts. SQLite is WAL-backed for crash
resilience and concurrent short-lived connections.
"""
import hashlib
import json
import math
import re
import sqlite3
from collections import defaultdict
import time
from pathlib import Path
from typing import Any
from dataclasses import asdict

from app.knowledge.memory_models import MemoryCandidate, MemoryHit, MemoryItem
from app.intelligence.understanding import normalize
from app.knowledge.memory_retrieval import search as hybrid_search
from app.knowledge.memory_extraction import extract as extract_memory_candidates
from app.knowledge.temporal_memory import project

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "memory.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    ts TEXT,
    importance INTEGER NOT NULL DEFAULT 3,
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'user',
    confidence REAL NOT NULL DEFAULT 1.0,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed TEXT
);
CREATE TABLE IF NOT EXISTS facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    ts TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL DEFAULT 'user',
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS fact_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT,
    status TEXT NOT NULL,
    ts TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, goal TEXT, status TEXT,
    plan TEXT, message TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS tool_outcomes (
    tool TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    ts TEXT
);
CREATE TABLE IF NOT EXISTS algorithm_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context TEXT NOT NULL,
    method TEXT NOT NULL,
    reward REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}',
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_algorithm_observations_context_method
    ON algorithm_observations(context, method, id);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT,
    payload TEXT,
    ts TEXT
);
CREATE TABLE IF NOT EXISTS runtime_runs (
    run_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, goal TEXT NOT NULL, status TEXT NOT NULL,
    started_at TEXT NOT NULL, updated_at TEXT NOT NULL, plan TEXT, final_message TEXT,
    plan_revision INTEGER NOT NULL DEFAULT 1, session_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_runtime_runs_session_status ON runtime_runs(session_id, status, updated_at);
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id TEXT PRIMARY KEY, goal TEXT NOT NULL, plan TEXT NOT NULL, outputs TEXT NOT NULL,
    world TEXT NOT NULL, next_index INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
    updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, state_hash TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL, tool TEXT NOT NULL, args TEXT NOT NULL, output TEXT,
    ok INTEGER NOT NULL, verified INTEGER NOT NULL DEFAULT 0, error TEXT,
    duration_ms REAL NOT NULL DEFAULT 0, ts TEXT NOT NULL,
    state_before TEXT, state_after TEXT
);
CREATE INDEX IF NOT EXISTS idx_effects_run ON effects(run_id, id);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, id);
CREATE TABLE IF NOT EXISTS plan_cache (
    goal_key TEXT PRIMARY KEY,
    plan TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    avg_cost REAL NOT NULL DEFAULT 0,
    avg_duration REAL NOT NULL DEFAULT 0,
    last_used TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    started_at REAL,
    updated_at REAL NOT NULL,
    heartbeat_at REAL NOT NULL,
    progress_at REAL NOT NULL,
    state TEXT,
    error TEXT,
    lease_owner TEXT,
    lease_expires_at REAL,
    revision INTEGER NOT NULL DEFAULT 1,
    owner_id TEXT,
    session_token_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_tasks_session_updated ON api_tasks(session_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_tasks_active ON api_tasks(status, updated_at DESC);
CREATE TABLE IF NOT EXISTS api_idempotency (
    route TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    task_id TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(route, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_api_idempotency_task ON api_idempotency(task_id);
CREATE TABLE IF NOT EXISTS api_approvals (
    task_id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    args TEXT NOT NULL DEFAULT '{}',
    decision INTEGER,
    expires_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_api_approvals_expires ON api_approvals(expires_at);
"""

ADVANCED_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_items (
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
CREATE INDEX IF NOT EXISTS idx_memory_items_lookup ON memory_items(status, scope, kind);
CREATE INDEX IF NOT EXISTS idx_memory_items_key ON memory_items(key, scope, status);
CREATE INDEX IF NOT EXISTS idx_memory_items_expiry ON memory_items(expires_at, status);
CREATE TABLE IF NOT EXISTS memory_history (
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
CREATE INDEX IF NOT EXISTS idx_memory_history_memory ON memory_history(memory_id, id);
CREATE TABLE IF NOT EXISTS memory_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    run_id TEXT,
    user_text TEXT NOT NULL,
    assistant_text TEXT,
    outcome TEXT,
    summary TEXT,
    ts TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memory_episodes_session ON memory_episodes(session_id, id);
CREATE INDEX IF NOT EXISTS idx_memory_episodes_run ON memory_episodes(run_id, id);
CREATE TABLE IF NOT EXISTS memory_working (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'context',
    content TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memory_working_session ON memory_working(session_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS memory_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'entity',
    scope TEXT NOT NULL DEFAULT 'global',
    aliases TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(canonical, scope)
);
CREATE INDEX IF NOT EXISTS idx_memory_entities_lookup ON memory_entities(canonical, scope);
CREATE TABLE IF NOT EXISTS memory_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    predicate TEXT NOT NULL,
    object_value TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'global',
    confidence REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    valid_at TEXT,
    invalid_at TEXT,
    source_memory_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memory_relations_subject ON memory_relations(subject_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_relations_object ON memory_relations(object_value, scope, status);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _tokens(text: str) -> list[str]:
    from app.intelligence.understanding import normalize
    n = normalize(text)
    return re.findall(r"[\w\u0600-\u06ff]+", n, flags=re.UNICODE)


class Memory:
    _KEY_ALIASES = {
        "my name": "name",
        "my full name": "name",
        "الاسم": "name",
        "اسمي": "name",
        "مدينتي": "city",
        "مدينتى": "city",
        "my favorite language": "favorite programming language",
        "favorite language": "favorite programming language",
        "my programming language": "favorite programming language",
        "where am i from": "origin",
        "where do i come from": "origin",
        "what is my origin": "origin",
        "my origin": "origin",
        "preferred theme": "theme",
        "my preferred theme": "theme",
        "favorite theme": "theme",
        "my favorite theme": "theme",
        "theme": "theme",
        "من انا": "origin",
        "من أنا": "origin",
        "انا من فين": "origin",
    }

    @classmethod
    def canonical_key(cls, raw: str) -> str:
        key = re.sub(r"\s+", " ", str(raw or "").strip(" \t:،,؟?"))
        if key.casefold().startswith("my "):
            key = key[3:].strip()
        return cls._KEY_ALIASES.get(key.casefold(), key.casefold())

    @classmethod
    def key_aliases(cls, raw: str) -> list[str]:
        canonical = cls.canonical_key(raw)
        aliases: list[str] = []
        if canonical in {"city", "hometown", "home city", "home_city", "location"}:
            aliases.append("origin")
        if canonical == "origin":
            aliases.extend(("city", "hometown", "home city"))
        return aliases

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            with conn:
                conn.executescript(SCHEMA)
                conn.executescript(ADVANCED_SCHEMA)
                self._migrate(conn)
                self._backfill_memory_items(conn)
                self._sanitize_legacy_placeholders(conn)
        finally:
            conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @staticmethod
    def _migrate(conn):
        # Existing V6/V7 databases may have the original narrow tables.
        columns = {r[1] for r in conn.execute("PRAGMA table_info(notes)")}
        for name, typ, default in [
            ("importance", "INTEGER", "3"), ("tags", "TEXT", "'[]'"),
            ("status", "TEXT", "'active'"), ("source", "TEXT", "'user'"),
            ("confidence", "REAL", "1.0"), ("access_count", "INTEGER", "0"),
            ("last_accessed", "TEXT", "NULL"),
        ]:
            if name not in columns:
                conn.execute(f"ALTER TABLE notes ADD COLUMN {name} {typ} DEFAULT {default}")
        columns = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
        for name, typ, default in [("status", "TEXT", "'active'"), ("confidence", "REAL", "1.0"),
                                   ("source", "TEXT", "'user'"), ("revision", "INTEGER", "1")]:
            if name not in columns:
                conn.execute(f"ALTER TABLE facts ADD COLUMN {name} {typ} DEFAULT {default}")
        columns = {r[1] for r in conn.execute("PRAGMA table_info(runtime_runs)")}
        if "plan_revision" not in columns:
            conn.execute("ALTER TABLE runtime_runs ADD COLUMN plan_revision INTEGER DEFAULT 1")
        if "session_id" not in columns:
            conn.execute("ALTER TABLE runtime_runs ADD COLUMN session_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runtime_runs_session_status ON runtime_runs(session_id, status, updated_at)")
        columns = {r[1] for r in conn.execute("PRAGMA table_info(checkpoints)")}
        if "revision" not in columns:
            conn.execute("ALTER TABLE checkpoints ADD COLUMN revision INTEGER DEFAULT 1")
        if "state_hash" not in columns:
            conn.execute("ALTER TABLE checkpoints ADD COLUMN state_hash TEXT DEFAULT ''")
        columns = {r[1] for r in conn.execute("PRAGMA table_info(effects)")}
        if "state_before" not in columns:
            conn.execute("ALTER TABLE effects ADD COLUMN state_before TEXT")
        if "state_after" not in columns:
            conn.execute("ALTER TABLE effects ADD COLUMN state_after TEXT")
        columns = {r[1] for r in conn.execute("PRAGMA table_info(api_tasks)")}
        if "lease_owner" not in columns:
            conn.execute("ALTER TABLE api_tasks ADD COLUMN lease_owner TEXT")
        if "lease_expires_at" not in columns:
            conn.execute("ALTER TABLE api_tasks ADD COLUMN lease_expires_at REAL")
        if "owner_id" not in columns:
            conn.execute("ALTER TABLE api_tasks ADD COLUMN owner_id TEXT")
        if "session_token_hash" not in columns:
            conn.execute("ALTER TABLE api_tasks ADD COLUMN session_token_hash TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_api_tasks_lease ON api_tasks(status, lease_expires_at)")

    @staticmethod
    def _sanitize_legacy_placeholders(conn):
        """Archive known malformed placeholder memories introduced by older parsers."""
        now = _now()
        rows = conn.execute(
            "SELECT id,revision,value FROM memory_items WHERE status='active' AND key='name' AND trim(value) IN ('?', '؟؟', '')"
        ).fetchall()
        for mid, revision, value in rows:
            conn.execute("UPDATE memory_items SET status='archived',invalid_at=?,updated_at=? WHERE id=?", (now, now, mid))
            conn.execute(
                "INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts) VALUES(?,?,?,?,?,?,?,?)",
                (mid, revision, "SANITIZE", value, None, "legacy_placeholder_cleanup", "system", now),
            )
        conn.execute("UPDATE facts SET status='deleted',ts=? WHERE key='name' AND trim(value) IN ('?', '؟؟', '')", (now,))

    @staticmethod
    def _backfill_memory_items(conn):
        # Preserve V6-V22 data in the richer memory model without deleting the legacy tables.
        conn.execute("""
            INSERT INTO memory_items(kind,key,value,normalized,scope,source,confidence,importance,status,created_at,updated_at,revision,metadata)
            SELECT 'note', NULL, n.text, lower(trim(n.text)), 'global', n.source, n.confidence, n.importance, n.status, COALESCE(n.ts, ?), COALESCE(n.ts, ?), 1,
                   json_object('legacy_note_id', n.id, 'tags', n.tags)
            FROM notes n
            WHERE NOT EXISTS (
                SELECT 1 FROM memory_items mi WHERE mi.kind='note' AND mi.value=n.text AND json_extract(mi.metadata,'$.legacy_note_id')=n.id
            )
        """, (_now(), _now()))
        conn.execute("""
            INSERT INTO memory_items(kind,key,value,normalized,scope,source,confidence,importance,status,created_at,updated_at,revision,metadata)
            SELECT 'fact', f.key, f.value, lower(trim(f.key || ' ' || f.value)), 'global', f.source, f.confidence, 5, f.status, COALESCE(f.ts, ?), COALESCE(f.ts, ?), f.revision,
                   json_object('legacy_fact', 1)
            FROM facts f
            WHERE NOT EXISTS (
                SELECT 1 FROM memory_items mi WHERE mi.kind='fact' AND mi.key=f.key AND mi.revision=f.revision
            )
        """, (_now(), _now()))

    def _q(self, sql: str, params=()):
        conn = self._connect()
        try:
            with conn:
                return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def add_note(self, text: str, importance: int = 3, tags=(), source: str = "user", confidence: float = 1.0) -> int:
        text = str(text).strip()
        if not text:
            raise ValueError("الملاحظة فاضية")
        from app.knowledge.memory_extraction import contains_secret_pattern
        if contains_secret_pattern(text):
            raise ValueError("لا يمكن حفظ أسرار أو بيانات اعتماد في ذاكرة الوكيل")
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO notes(text, ts, importance, tags, status, source, confidence) VALUES (?,?,?,?,?,?,?)",
                    (text, _now(), max(1, min(5, int(importance))), json.dumps(list(tags), ensure_ascii=False),
                     "active", source, float(confidence)),
                )
                note_id = int(cur.lastrowid)
        finally:
            conn.close()
        self.remember(text, kind="note", source=source, confidence=confidence, importance=importance,
                      metadata={"legacy_note_id": note_id, "tags": list(tags)}, reason="add_note")
        return note_id

    def list_notes(self) -> list[str]:
        return [r[0] for r in self._q("SELECT text FROM notes WHERE status='active' ORDER BY id")]

    def search_notes(self, query: str, top_k: int = 10) -> list[str]:
        hits = self.search_memory(query, top_k=top_k, kinds={"note"}, scope="global")
        if hits:
            return [h["value"] for h in hits]
        # Legacy fallback for databases where note backfill has not yet happened.
        q_tokens = _tokens(query)
        if not q_tokens:
            return []
        rows = self._q("SELECT id,text,ts,importance FROM notes WHERE status='active' ORDER BY id")
        scored=[]
        for rid,text,ts,importance in rows:
            toks=set(_tokens(text)); overlap=len(set(q_tokens)&toks)
            if overlap:
                scored.append((overlap,int(importance),rid,text))
        scored.sort(key=lambda x:(-x[0],-x[1],x[2]))
        return [x[3] for x in scored[:top_k]]

    def set_fact(self, key: str, value: str, source: str = "user", confidence: float = 1.0):
        key = str(key).strip()
        value = str(value).strip()
        if not key or not value:
            raise ValueError("fact key/value cannot be empty")
        old = self._q("SELECT value,revision,status FROM facts WHERE key=?", (key,))
        revision = int(old[0][1]) + 1 if old else 1
        conn = self._connect()
        try:
            with conn:
                if old:
                    conn.execute("INSERT INTO fact_history(key,value,status,ts,source) VALUES(?,?,?,?,?)",
                                 (key, old[0][0], "superseded" if old[0][2] == "active" else old[0][2], _now(), source))
                conn.execute("INSERT OR REPLACE INTO facts(key,value,ts,status,confidence,source,revision) VALUES (?,?,?,?,?,?,?)",
                             (key, value, _now(), "active", float(confidence), source, revision))
        finally:
            conn.close()
        self.remember(value, kind="fact", key=key, source=source, confidence=confidence, importance=5,
                      metadata={"legacy_fact": 1}, reason="set_fact")

    def get_fact(self, key: str) -> str | None:
        now = _now()
        rows = self._q("SELECT value FROM memory_items WHERE kind='fact' AND key=? AND status='active' AND (valid_at IS NULL OR valid_at <= ?) AND (expires_at IS NULL OR expires_at >= ?) AND (invalid_at IS NULL OR invalid_at > ?) ORDER BY revision DESC LIMIT 1", (key, now, now, now))
        if rows:
            return rows[0][0]
        rows = self._q("SELECT value FROM facts WHERE key = ? AND status='active'", (key,))
        return rows[0][0] if rows else None

    def delete_fact(self, key: str) -> bool:
        rows = self._q("SELECT value FROM facts WHERE key=? AND status='active'", (key,))
        memory_rows = self._q("SELECT id,value,revision FROM memory_items WHERE kind='fact' AND key=? AND status='active'", (key,))
        if not rows and not memory_rows:
            return False
        conn = self._connect()
        try:
            with conn:
                if rows:
                    conn.execute("INSERT INTO fact_history(key,value,status,ts,source) VALUES(?,?,?,?,?)",
                                 (key, rows[0][0], "deleted", _now(), "user"))
                    conn.execute("UPDATE facts SET status='deleted', ts=? WHERE key=?", (_now(), key))
                for mid, value, revision in memory_rows:
                    conn.execute("UPDATE memory_items SET status='deleted', invalid_at=?, updated_at=? WHERE id=?", (_now(), _now(), mid))
                    conn.execute("INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts) VALUES(?,?,?,?,?,?,?,?)",
                                 (mid, revision, "DELETE", value, None, "forget_fact", "user", _now()))
        finally:
            conn.close()
        return True

    def record_algorithm_observation(self, context: str, method: str, reward: float,
                                    verified: bool = False, metadata: dict | None = None):
        reward_value = max(0.0, min(1.0, float(reward)))
        self._q(
            "INSERT INTO algorithm_observations(context,method,reward,verified,metadata,ts) VALUES (?,?,?,?,?,?)",
            (context, method, reward_value, 1 if verified else 0,
             json.dumps(metadata or {}, ensure_ascii=False, default=str), _now()),
        )

    def algorithm_observations(self, context: str, method: str, limit: int = 200) -> list[dict]:
        rows = self._q(
            "SELECT reward,verified,metadata,ts FROM algorithm_observations "
            "WHERE context=? AND method=? ORDER BY id DESC LIMIT ?",
            (context, method, int(limit)),
        )
        out = []
        for reward, verified, metadata, ts in reversed(rows):
            try:
                md = json.loads(metadata) if metadata else {}
            except Exception:
                md = {}
            out.append({"reward": float(reward), "verified": bool(verified), "metadata": md, "ts": ts})
        return out

    def algorithm_portfolio_snapshot(self) -> list[dict]:
        rows = self._q(
            "SELECT context,method,COUNT(*),AVG(reward),SUM(verified),MAX(ts) "
            "FROM algorithm_observations GROUP BY context,method ORDER BY context,method"
        )
        return [
            {"context": c, "method": m, "observations": n, "mean_reward": mean_reward,
             "verified_observations": verified, "last_seen": last_seen}
            for c, m, n, mean_reward, verified, last_seen in rows
        ]

    def record_tool_outcome(self, tool: str, ok: bool):
        self._q("INSERT OR IGNORE INTO tool_outcomes(tool, attempts, successes, failures, ts) VALUES (?,0,0,0,?)", (tool, _now()))
        self._q("UPDATE tool_outcomes SET attempts=attempts+1, successes=successes+?, failures=failures+?, ts=? WHERE tool=?",
                (1 if ok else 0, 0 if ok else 1, _now(), tool))

    def tool_reliability(self, tool: str) -> float:
        rows = self._q("SELECT attempts, successes FROM tool_outcomes WHERE tool=?", (tool,))
        if not rows or rows[0][0] == 0:
            return 1.0
        return rows[0][1] / rows[0][0]

    def tool_reliability_posterior(self, tool: str) -> float:
        """Bayesian-smoothed reliability estimate using a Beta(1,1) prior."""
        rows = self._q("SELECT attempts, successes FROM tool_outcomes WHERE tool=?", (tool,))
        if not rows:
            return 0.5
        attempts, successes = rows[0]
        return (float(successes) + 1.0) / (float(attempts) + 2.0)

    def reliability_snapshot(self) -> dict[str, dict[str, float]]:
        rows = self._q("SELECT tool,attempts,successes,failures FROM tool_outcomes ORDER BY tool")
        return {tool: {"attempts": attempts, "successes": successes, "failures": failures,
                       "reliability": successes / attempts if attempts else 1.0}
                for tool, attempts, successes, failures in rows}

    def record_event(self, kind: str, payload: dict):
        from app.production.redaction import redact
        safe_payload = redact(payload)
        self._q("INSERT INTO events(kind, payload, ts) VALUES (?, ?, ?)",
                (kind, json.dumps(safe_payload, ensure_ascii=False, default=str), _now()))

    def record_run(self, goal: str, status: str, plan: dict, message: str):
        self._q("INSERT INTO runs(goal, status, plan, message, ts) VALUES (?, ?, ?, ?, ?)",
                (goal, status, json.dumps(plan, ensure_ascii=False, default=str), message, _now()))

    # --- Production API durability / idempotency ---
    def create_api_task(self, *, task_id: str, message: str, session_id: str, owner_id: str | None = None, session_token_hash: str | None = None) -> dict:
        now = time.time()
        payload = {
            "task_id": str(task_id), "session_id": str(session_id), "message": str(message),
            "status": "queued", "created_at": now, "started_at": None,
            "updated_at": now, "heartbeat_at": now, "progress_at": now,
            "state": None, "error": None, "lease_owner": None, "lease_expires_at": None, "revision": 1, "owner_id": owner_id, "session_token_hash": session_token_hash,
        }
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO api_tasks(task_id,session_id,message,status,created_at,started_at,updated_at,heartbeat_at,progress_at,state,error,lease_owner,lease_expires_at,revision,owner_id,session_token_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (payload["task_id"], payload["session_id"], payload["message"], payload["status"],
                     payload["created_at"], payload["started_at"], payload["updated_at"], payload["heartbeat_at"],
                     payload["progress_at"], None, None, None, None, 1, payload["owner_id"], payload["session_token_hash"]),
                )
        finally:
            conn.close()
        return payload

    def create_idempotent_api_task(self, *, route: str, idempotency_key: str, request_hash: str,
                                   task_id: str, message: str, session_id: str, response: dict,
                                   owner_id: str | None = None, session_token_hash: str | None = None) -> tuple[str, dict]:
        """Atomically claim an idempotency key and create its task.

        Returns (new|replay|conflict, record). A matching retry never creates another task.
        """
        now = time.time()
        response_json = json.dumps(response, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT request_hash,task_id,response,created_at,updated_at FROM api_idempotency WHERE route=? AND idempotency_key=?",
                (route, idempotency_key),
            ).fetchone()
            if existing:
                conn.rollback()
                task_owner = conn.execute("SELECT owner_id FROM api_tasks WHERE task_id=?", (existing[1],)).fetchone()
                if owner_id and task_owner and task_owner[0] and task_owner[0] != owner_id:
                    return "forbidden", {"task_id": existing[1]}
                if existing[0] != request_hash:
                    return "conflict", {"task_id": existing[1], "response": json.loads(existing[2])}
                return "replay", {"task_id": existing[1], "response": json.loads(existing[2])}
            conn.execute(
                "INSERT INTO api_tasks(task_id,session_id,message,status,created_at,started_at,updated_at,heartbeat_at,progress_at,state,error,lease_owner,lease_expires_at,revision,owner_id,session_token_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, session_id, message, "queued", now, None, now, now, now, None, None, None, None, 1, owner_id, session_token_hash),
            )
            conn.execute(
                "INSERT INTO api_idempotency(route,idempotency_key,request_hash,task_id,response,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (route, idempotency_key, request_hash, task_id, response_json, now, now),
            )
            conn.commit()
            return "new", {"task_id": task_id, "response": dict(response)}
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def get_api_task(self, task_id: str, *, owner_id: str | None = None, session_token_hash: str | None = None) -> dict | None:
        sql = "SELECT task_id,session_id,message,status,created_at,started_at,updated_at,heartbeat_at,progress_at,state,error,lease_owner,lease_expires_at,revision,owner_id,session_token_hash FROM api_tasks WHERE task_id=?"
        params: tuple[object, ...] = (task_id,)
        if owner_id:
            sql += " AND owner_id=?"
            params += (owner_id,)
        if session_token_hash:
            sql += " AND session_token_hash=?"
            params += (session_token_hash,)
        rows = self._q(sql, params)
        if not rows:
            return None
        row = rows[0]
        return self._api_task_row(row)

    @staticmethod
    def _api_task_row(row) -> dict:
        task_id, session_id, message, status, created_at, started_at, updated_at, heartbeat_at, progress_at, state, error, lease_owner, lease_expires_at, revision, owner_id, session_token_hash = row
        try:
            state_value = json.loads(state) if state else None
        except Exception:
            state_value = None
        return {
            "task_id": task_id, "session_id": session_id, "message": message, "status": status,
            "created_at": created_at, "started_at": started_at, "updated_at": updated_at,
            "heartbeat_at": heartbeat_at, "progress_at": progress_at, "state": state_value,
            "error": error, "lease_owner": lease_owner, "lease_expires_at": lease_expires_at, "revision": revision, "owner_id": owner_id, "session_token_hash": session_token_hash,
        }

    def update_api_task(self, task_id: str, **changes: Any) -> dict | None:
        allowed = {"status", "started_at", "state", "error", "heartbeat_at", "progress_at", "lease_owner", "lease_expires_at"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported api task fields: {sorted(unknown)}")
        now = time.time()
        fields = []
        values = []
        for key, value in changes.items():
            if key == "state":
                value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) if value is not None else None
            fields.append(f"{key}=?")
            values.append(value)
        fields.extend(["updated_at=?", "heartbeat_at=?", "progress_at=?", "revision=revision+1"])
        values.extend([now, now, now, task_id])
        conn = self._connect()
        try:
            with conn:
                conn.execute(f"UPDATE api_tasks SET {', '.join(fields)} WHERE task_id=?", values)
        finally:
            conn.close()
        return self.get_api_task(task_id)

    def heartbeat_api_task(self, task_id: str) -> dict | None:
        now = time.time()
        self._q("UPDATE api_tasks SET heartbeat_at=?,updated_at=?,revision=revision+1 WHERE task_id=? AND status IN ('queued','running','waiting_approval')", (now, now, task_id))
        return self.get_api_task(task_id)

    def claim_api_task_lease(self, task_id: str, lease_owner: str, lease_seconds: float) -> bool:
        now = time.time()
        expires = now + max(5.0, float(lease_seconds))
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE api_tasks SET status='running', started_at=COALESCE(started_at, ?), lease_owner=?, lease_expires_at=?, updated_at=?, heartbeat_at=?, progress_at=?, revision=revision+1 "
                    "WHERE task_id=? AND status IN ('queued','running') AND (lease_owner IS NULL OR lease_expires_at IS NULL OR lease_expires_at<=? OR lease_owner=?)",
                    (now, str(lease_owner), expires, now, now, now, task_id, now, str(lease_owner)),
                )
                return cur.rowcount == 1
        finally:
            conn.close()

    def renew_api_task_lease(self, task_id: str, lease_owner: str, lease_seconds: float) -> bool:
        now = time.time()
        expires = now + max(5.0, float(lease_seconds))
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE api_tasks SET lease_expires_at=?,updated_at=?,heartbeat_at=?,revision=revision+1 WHERE task_id=? AND status IN ('running','waiting_approval') AND lease_owner=?",
                    (expires, now, now, task_id, str(lease_owner)),
                )
                return cur.rowcount == 1
        finally:
            conn.close()

    def release_api_task_lease(self, task_id: str, lease_owner: str) -> bool:
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE api_tasks SET lease_owner=NULL,lease_expires_at=NULL,updated_at=?,revision=revision+1 WHERE task_id=? AND lease_owner=?",
                    (time.time(), task_id, str(lease_owner)),
                )
                return cur.rowcount == 1
        finally:
            conn.close()

    def api_task_execution_active(self, task_id: str, lease_owner: str) -> bool:
        rows = self._q(
            "SELECT status,lease_owner,lease_expires_at FROM api_tasks WHERE task_id=?", (task_id,)
        )
        if not rows:
            return False
        status, owner, expires = rows[0]
        return str(status) in {"running", "waiting_approval"} and str(owner or "") == str(lease_owner) and float(expires or 0.0) > time.time()

    def latest_api_task(self, session_id: str, *, owner_id: str | None = None, session_token_hash: str | None = None) -> dict | None:
        sql = "SELECT task_id,session_id,message,status,created_at,started_at,updated_at,heartbeat_at,progress_at,state,error,lease_owner,lease_expires_at,revision,owner_id,session_token_hash FROM api_tasks WHERE session_id=?"
        params: tuple[object, ...] = (session_id,)
        if owner_id:
            sql += " AND owner_id=?"
            params += (owner_id,)
        if session_token_hash:
            sql += " AND session_token_hash=?"
            params += (session_token_hash,)
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT 1"
        rows = self._q(sql, params)
        return self._api_task_row(rows[0]) if rows else None

    def active_api_task_count(self) -> int:
        rows = self._q("SELECT COUNT(*) FROM api_tasks WHERE status IN ('queued','running','waiting_approval')")
        return int(rows[0][0]) if rows else 0

    def claim_api_approval(self, *, task_id: str, tool: str, args: dict, expires_at: float) -> dict:
        now = time.time()
        from app.production.redaction import redact
        safe_args = json.dumps(redact(args), ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO api_approvals(task_id,tool,args,decision,expires_at,updated_at,revision) VALUES(?,?,?,?,?,?,1) ON CONFLICT(task_id) DO UPDATE SET tool=excluded.tool,args=excluded.args,decision=NULL,expires_at=excluded.expires_at,updated_at=excluded.updated_at,revision=api_approvals.revision+1",
                    (task_id, tool, safe_args, None, float(expires_at), now),
                )
        finally:
            conn.close()
        return {"task_id": task_id, "tool": tool, "args": json.loads(safe_args), "decision": None, "expires_at": expires_at}

    def set_api_approval(self, task_id: str, decision: bool) -> bool:
        now = time.time()
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE api_approvals SET decision=?,updated_at=?,revision=revision+1 WHERE task_id=? AND expires_at>? AND decision IS NULL",
                    (1 if decision else 0, now, task_id, now),
                )
                return cur.rowcount == 1
        finally:
            conn.close()

    def get_api_approval(self, task_id: str) -> dict | None:
        rows = self._q("SELECT task_id,tool,args,decision,expires_at,updated_at,revision FROM api_approvals WHERE task_id=?", (task_id,))
        if not rows:
            return None
        tid, tool, args, decision, expires_at, updated_at, revision = rows[0]
        try:
            parsed_args = json.loads(args) if args else {}
        except Exception:
            parsed_args = {}
        return {"task_id": tid, "tool": tool, "args": parsed_args, "decision": None if decision is None else bool(decision),
                "expires_at": float(expires_at), "updated_at": updated_at, "revision": revision}

    def recent_runs(self, n: int = 5) -> list[dict]:
        rows = self._q("SELECT goal, status, ts FROM runs ORDER BY id DESC LIMIT ?", (n,))
        return [{"goal": g, "status": s, "ts": t} for g, s, t in rows]

    def start_run(self, run_id: str, trace_id: str, goal: str, plan: dict | None = None, session_id: str | None = None):
        now = _now()
        payload = json.dumps(plan or {"steps": []}, ensure_ascii=False, default=str)
        self._q("INSERT OR REPLACE INTO runtime_runs(run_id, trace_id, goal, status, started_at, updated_at, plan, final_message, plan_revision, session_id) VALUES (?,?,?,?,?,?,?,?,COALESCE((SELECT plan_revision FROM runtime_runs WHERE run_id=?),1),?)",
                (run_id, trace_id, goal, "running", now, now, payload, "", run_id, session_id))

    def update_run(self, run_id: str, status: str, plan: dict, final_message: str = ""):
        self._q("UPDATE runtime_runs SET status=?, updated_at=?, plan=?, final_message=?, plan_revision=plan_revision+1 WHERE run_id=?",
                (status, _now(), json.dumps(plan, ensure_ascii=False, default=str), final_message, run_id))

    def checkpoint(self, run_id: str, goal: str, plan: dict, outputs: dict, world: dict, next_index: int, status: str):
        state_payload = json.dumps({"plan": plan, "outputs": outputs, "world": world, "next_index": next_index, "status": status}, ensure_ascii=False, sort_keys=True, default=str)
        state_hash = hashlib.sha256(state_payload.encode("utf-8")).hexdigest()
        old = self._q("SELECT revision FROM checkpoints WHERE run_id=?", (run_id,))
        revision = int(old[0][0]) + 1 if old else 1
        self._q("INSERT OR REPLACE INTO checkpoints(run_id, goal, plan, outputs, world, next_index, status, updated_at, revision, state_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, goal, json.dumps(plan, ensure_ascii=False, default=str),
                 json.dumps(outputs, ensure_ascii=False, default=str), json.dumps(world, ensure_ascii=False, default=str),
                 next_index, status, _now(), revision, state_hash))

    def load_checkpoint(self, run_id: str) -> dict | None:
        rows = self._q("SELECT goal, plan, outputs, world, next_index, status, updated_at, revision, state_hash FROM checkpoints WHERE run_id=?", (run_id,))
        if not rows:
            return None
        goal, plan, outputs, world, next_index, status, updated_at, revision, state_hash = rows[0]
        payload = {"plan": json.loads(plan), "outputs": json.loads(outputs), "world": json.loads(world),
                   "next_index": next_index, "status": status}
        actual = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        if state_hash and actual != state_hash:
            raise ValueError("checkpoint integrity check failed")
        return {"goal": goal, **payload, "updated_at": updated_at, "revision": revision, "state_hash": state_hash}

    def record_effect(self, *, run_id: str, step_id: str, attempt: int, tool: str, args: dict,
                      output, ok: bool, verified: bool, error: str | None, duration_ms: float,
                      state_before: str | None = None, state_after: str | None = None) -> int:
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute("INSERT INTO effects(run_id, step_id, attempt, tool, args, output, ok, verified, error, duration_ms, ts, state_before, state_after) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, step_id, attempt, tool,
                     json.dumps(args, ensure_ascii=False, default=str), json.dumps(output, ensure_ascii=False, default=str),
                     1 if ok else 0, 1 if verified else 0, error, duration_ms, _now(), state_before, state_after))
                return int(cur.lastrowid)
        finally:
            conn.close()

    def update_effect_state_after(self, effect_id: int, state_after: str):
        self._q("UPDATE effects SET state_after=? WHERE id=?", (state_after, effect_id))

    def latest_effect(self, run_id: str, step_id: str) -> dict | None:
        rows = self._q("SELECT id,attempt,tool,args,output,ok,verified,error,duration_ms,ts,state_before,state_after FROM effects WHERE run_id=? AND step_id=? ORDER BY id DESC LIMIT 1", (run_id, step_id))
        if not rows:
            return None
        row_id, attempt, tool, args, output, ok, verified, error, duration_ms, ts, state_before, state_after = rows[0]
        return {"id": row_id, "attempt": attempt, "tool": tool, "args": json.loads(args),
                "output": json.loads(output) if output else None, "ok": bool(ok), "verified": bool(verified),
                "error": error, "duration_ms": duration_ms, "ts": ts,
                "state_before": state_before, "state_after": state_after}

    def recall_context(self, query: str, limit: int = 5, *, scope: str = "global", session_id: str | None = None) -> dict:
        """Unified recall across semantic, episodic, procedural, temporal, working and graph memory."""
        hits = self.search_memory(query, top_k=limit, scope=scope)
        semantic = [h for h in hits if h["kind"] in {"fact", "preference", "goal", "profile"}]
        notes = [h for h in hits if h["kind"] == "note"]
        episodic = self.recent_episodes(session_id=session_id, limit=max(limit, 8))
        if query:
            qt=set(_tokens(query))
            episodic=[e for e in episodic if not qt or qt & set(_tokens(e["user_text"] + " " + (e.get("summary") or "")))]
        procedural=[]
        cached=self.cached_plan(normalize(query))
        if cached:
            procedural.append({"goal_key":normalize(query),"success_count":cached["success_count"],"failure_count":cached["failure_count"],"avg_cost":cached["avg_cost"],"avg_duration":cached["avg_duration"]})
        temporal = project(self, query, limit)
        working = self.working_recall(session_id, limit) if session_id else []
        graph=[]
        for hit in semantic[:limit]:
            if hit.get("key"):
                graph.extend(self.graph(hit["key"], scope=scope, limit=limit))
        return {"semantic": semantic[:limit], "notes": notes[:limit], "episodic": episodic[:limit],
                "procedural": procedural[:limit], "temporal": temporal, "working": working[:limit], "graph": graph[:limit]}

    def routine_candidates(self, min_occurrences: int = 3, days: int = 30) -> list[dict]:
        from app.knowledge.learning import discover_routines
        return discover_routines(self, min_occurrences=min_occurrences, days=days)

    def effects(self, run_id: str) -> list[dict]:
        rows = self._q("SELECT step_id, attempt, tool, args, output, ok, verified, error, duration_ms, ts, state_before, state_after FROM effects WHERE run_id=? ORDER BY id", (run_id,))
        return [
            {"step_id": s, "attempt": a, "tool": t, "args": json.loads(args), "output": json.loads(out) if out else None,
             "ok": bool(ok), "verified": bool(v), "error": e, "duration_ms": d, "ts": ts,
             "state_before": sb, "state_after": sa}
            for s, a, t, args, out, ok, v, e, d, ts, sb, sa in rows
        ]

    # --- Advanced memory system ---
    def _memory_row_to_item(self, row) -> MemoryItem:
        (mid, kind, key, value, scope, session_id, run_id, source, source_ref, confidence,
         importance, sensitivity, status, created_at, updated_at, valid_at, invalid_at,
         expires_at, last_accessed, access_count, revision, supersedes_id, metadata) = row
        try:
            md = json.loads(metadata) if metadata else {}
        except Exception:
            md = {}
        return MemoryItem(
            id=int(mid), kind=kind, key=key, value=value, scope=scope,
            session_id=session_id, run_id=run_id, source=source, source_ref=source_ref,
            confidence=float(confidence), importance=int(importance), sensitivity=sensitivity,
            status=status, created_at=created_at, updated_at=updated_at, valid_at=valid_at,
            invalid_at=invalid_at, expires_at=expires_at, last_accessed=last_accessed,
            access_count=int(access_count), revision=int(revision), supersedes_id=supersedes_id,
            metadata=md,
        )

    def _active_memory_rows(self, *, scope: str | None = None, kinds: set[str] | None = None):
        where = ["status='active'"]
        params = []
        if scope:
            where.append("(scope=? OR scope='global')")
            params.append(scope)
        if kinds:
            marks = ','.join('?' for _ in kinds)
            where.append(f"kind IN ({marks})")
            params.extend(sorted(kinds))
        return self._q(
            "SELECT id,kind,key,value,scope,session_id,run_id,source,source_ref,confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,last_accessed,access_count,revision,supersedes_id,metadata "
            "FROM memory_items WHERE " + " AND ".join(where) + " ORDER BY updated_at DESC, id DESC", params)

    def remember(self, value: str, *, kind: str = "fact", key: str | None = None,
                 scope: str = "global", session_id: str | None = None,
                 run_id: str | None = None, source: str = "user", source_ref: str | None = None,
                 confidence: float = 1.0, importance: int = 3, sensitivity: str = "normal",
                 valid_at: str | None = None, invalid_at: str | None = None,
                 expires_at: str | None = None, metadata: dict | None = None,
                 reason: str = "remember") -> int:
        value = str(value).strip()
        if not value:
            raise ValueError("memory value is empty")
        from app.knowledge.memory_extraction import contains_secret_pattern
        if sensitivity == "secret" or contains_secret_pattern(value):
            raise ValueError("secret material cannot be persisted in agent memory")
        confidence = max(0.0, min(1.0, float(confidence)))
        importance = max(1, min(5, int(importance)))
        normalized = " ".join(_tokens((key or "") + " " + value))
        now = _now()
        conn = self._connect()
        try:
            with conn:
                old = None
                if key:
                    row = conn.execute(
                        "SELECT id,value,revision,confidence,importance,status FROM memory_items WHERE kind=? AND key=? AND scope=? AND status='active' ORDER BY revision DESC LIMIT 1",
                        (kind, key, scope)).fetchone()
                    old = row
                else:
                    row = conn.execute(
                        "SELECT id,value,revision,confidence,importance,status FROM memory_items WHERE kind=? AND key IS NULL AND scope=? AND status='active' AND normalized=? ORDER BY revision DESC LIMIT 1",
                        (kind, scope, normalized)).fetchone()
                    old = row
                if old and old[1].strip() == value:
                    current = conn.execute("SELECT source,source_ref,session_id,run_id,expires_at,metadata FROM memory_items WHERE id=?", (old[0],)).fetchone()
                    current = current or ("system", None, None, None, None, "{}")
                    source_rank = {"auto": 1, "system": 2, "user": 3}
                    kept_source = source if source_rank.get(source, 1) >= source_rank.get(current[0], 1) else current[0]
                    kept_source_ref = source_ref or current[1]
                    kept_session = session_id or current[2]
                    kept_run = run_id or current[3]
                    kept_expiry = expires_at or current[4]
                    kept_metadata = metadata if metadata else (json.loads(current[5]) if current[5] else {})
                    conn.execute(
                        "UPDATE memory_items SET confidence=?,importance=?,updated_at=?,source=?,source_ref=?,session_id=?,run_id=?,expires_at=?,metadata=? WHERE id=?",
                        (max(float(old[3]), confidence), max(int(old[4]), importance), now, kept_source, kept_source_ref, kept_session, kept_run,
                         kept_expiry, json.dumps(kept_metadata, ensure_ascii=False, default=str), old[0]))
                    conn.execute("INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts) VALUES(?,?,?,?,?,?,?,?)",
                                 (old[0], old[2], "CONFIRM", old[1], value, reason, source, now))
                    return int(old[0])
                revision = int(old[2]) + 1 if old else 1
                supersedes = int(old[0]) if old else None
                if old:
                    conn.execute("UPDATE memory_items SET status='superseded',invalid_at=?,updated_at=? WHERE id=?", (now, now, old[0]))
                    conn.execute("INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts) VALUES(?,?,?,?,?,?,?,?)",
                                 (old[0], old[2], "SUPERSEDE", old[1], value, reason, source, now))
                cur = conn.execute(
                    "INSERT INTO memory_items(kind,key,value,normalized,scope,session_id,run_id,source,source_ref,confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,revision,supersedes_id,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (kind, key, value, normalized, scope, session_id, run_id, source, source_ref, confidence, importance,
                     sensitivity, "active", now, now, valid_at, invalid_at, expires_at, revision, supersedes,
                     json.dumps(metadata or {}, ensure_ascii=False, default=str)),
                )
                mid = int(cur.lastrowid)
                conn.execute("INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts) VALUES(?,?,?,?,?,?,?,?)",
                             (mid, revision, "ADD" if old is None else "UPDATE", old[1] if old else None, value, reason, source, now))
                return mid
        finally:
            conn.close()

    def add_memory_candidate(self, candidate: MemoryCandidate, **kwargs) -> int:
        return self.remember(candidate.value, kind=candidate.kind, key=candidate.key,
                             confidence=candidate.confidence, importance=candidate.importance,
                             source=candidate.source, sensitivity=candidate.sensitivity,
                             valid_at=candidate.valid_at, invalid_at=candidate.invalid_at,
                             expires_at=candidate.expires_at, metadata=candidate.metadata, **kwargs)

    def search_memory(self, query: str, *, top_k: int = 8, kinds: set[str] | None = None,
                      scope: str = "global", include_expired: bool = False) -> list[dict]:
        rows = self._active_memory_rows(scope=scope, kinds=kinds)
        items = [self._memory_row_to_item(r) for r in rows]
        if kinds is None or "episode" in kinds:
            episode_rows = self._q("SELECT id,session_id,run_id,user_text,assistant_text,outcome,summary,ts,metadata FROM memory_episodes ORDER BY id DESC LIMIT 500")
            for eid, sid, rid, user_text, assistant_text, outcome, summary, ts, metadata in episode_rows:
                if outcome not in (None, "completed"):
                    continue
                if scope != "global" and sid not in (None, scope):
                    continue
                try: md = json.loads(metadata) if metadata else {}
                except Exception: md = {}
                md = dict(md)
                md.setdefault("entities", [])
                item = MemoryItem(id=-int(eid), kind="episode", key=None,
                                  value=(summary or user_text or "").strip(), scope=scope, session_id=sid, run_id=rid,
                                  source="episode", source_ref=f"episode:{eid}", confidence=1.0, importance=3,
                                  sensitivity="normal", status="active", created_at=ts, updated_at=ts,
                                  metadata={**md, "assistant_text": assistant_text, "outcome": outcome})
                items.append(item)
        hits = hybrid_search(items, query, top_k=top_k, kinds=kinds, scope=scope, include_expired=include_expired)
        if not hits:
            return []
        ids = [h.item.id for h in hits]
        conn = self._connect()
        try:
            with conn:
                marks = ','.join('?' for _ in ids)
                conn.execute(f"UPDATE memory_items SET access_count=access_count+1,last_accessed=? WHERE id IN ({marks})", (_now(), *ids))
        finally:
            conn.close()
        return [
            {"id": h.item.id, "kind": h.item.kind, "key": h.item.key, "value": h.item.value,
             "scope": h.item.scope, "source": h.item.source, "confidence": h.item.confidence,
             "importance": h.item.importance, "status": h.item.status, "revision": h.item.revision,
             "valid_at": h.item.valid_at, "invalid_at": h.item.invalid_at, "expires_at": h.item.expires_at,
             "created_at": h.item.created_at, "updated_at": h.item.updated_at, "score": round(h.score, 4),
             "reasons": list(h.reasons), "metadata": h.item.metadata}
            for h in hits
        ]

    def list_memories(self, *, kind: str | None = None, scope: str = "global", limit: int = 100,
                      include_archived: bool = False) -> list[dict]:
        where = []
        params = []
        if not include_archived:
            now = _now()
            where.append("status='active'")
            where.append("(valid_at IS NULL OR valid_at <= ?)")
            params.append(now)
            where.append("(invalid_at IS NULL OR invalid_at > ?)")
            params.append(now)
            where.append("(expires_at IS NULL OR expires_at >= ?)")
            params.append(now)
        else:
            # Archived/deleted history remains queryable only when explicitly requested.
            pass
        if kind:
            where.append("kind=?")
            params.append(kind)
        if scope:
            where.append("(scope=? OR scope='global')")
            params.append(scope)
        sql = "SELECT id,kind,key,value,scope,source,confidence,importance,status,revision,valid_at,invalid_at,expires_at,updated_at,metadata FROM memory_items"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY importance DESC, updated_at DESC, id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        rows = self._q(sql, params)
        out = []
        for row in rows:
            try: md = json.loads(row[-1]) if row[-1] else {}
            except Exception: md = {}
            out.append({"id": row[0], "kind": row[1], "key": row[2], "value": row[3], "scope": row[4],
                        "source": row[5], "confidence": row[6], "importance": row[7], "status": row[8],
                        "revision": row[9], "valid_at": row[10], "invalid_at": row[11], "expires_at": row[12],
                        "updated_at": row[13], "metadata": md})
        return out

    def get_memory(self, memory_id: int, *, include_inactive: bool = False) -> dict | None:
        sql = "SELECT id,kind,key,value,scope,session_id,run_id,source,source_ref,confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,last_accessed,access_count,revision,supersedes_id,metadata FROM memory_items WHERE id=?"
        params = (int(memory_id),)
        if not include_inactive:
            sql += " AND status='active'"
        rows = self._q(sql, params)
        if not rows:
            return None
        return asdict(self._memory_row_to_item(rows[0]))

    def memory_history(self, *, memory_id: int | None = None, key: str | None = None, scope: str = "global", limit: int = 50) -> list[dict]:
        where, params = [], []
        if memory_id is not None:
            where.append("memory_id=?")
            params.append(int(memory_id))
        elif key:
            where.append("memory_id IN (SELECT id FROM memory_items WHERE key=? AND (scope=? OR scope='global'))")
            params.extend([key, scope])
        else:
            where.append("memory_id IN (SELECT id FROM memory_items WHERE scope=? OR scope='global')")
            params.append(scope)
        sql = "SELECT memory_id,revision,action,old_value,new_value,reason,source,ts FROM memory_history"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        rows = self._q(sql, params)
        return [{"memory_id": r[0], "revision": r[1], "action": r[2], "old_value": r[3], "new_value": r[4],
                 "reason": r[5], "source": r[6], "ts": r[7]} for r in rows]

    def forget_memory(self, memory_id: int, *, reason: str = "user_forget") -> bool:
        row = self._q("SELECT value,revision,status FROM memory_items WHERE id=?", (int(memory_id),))
        if not row or row[0][2] != "active":
            return False
        now = _now()
        self._q("UPDATE memory_items SET status='deleted',invalid_at=?,updated_at=? WHERE id=?", (now, now, int(memory_id)))
        self._q("INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts) VALUES(?,?,?,?,?,?,?,?)",
                (int(memory_id), row[0][1], "DELETE", row[0][0], None, reason, "user", now))
        return True

    def forget_all(self, *, scope: str = "global", include_episodes: bool = True) -> dict:
        """Delete all active personal-memory content in the selected scope.

        The action is intentionally separate from archival/cleanup and is approval-gated
        at the tool layer. Memory history is kept as a minimal audit trail.
        """
        rows = self._q("SELECT id FROM memory_items WHERE status='active' AND (scope=? OR scope='global')", (scope,))
        deleted_items = 0
        for (mid,) in rows:
            deleted_items += int(self.forget_memory(mid, reason="user_forget_all"))
        self._q("UPDATE facts SET status='deleted',ts=? WHERE status='active'", (_now(),))
        deleted_episodes = 0
        if include_episodes:
            count = self._q("SELECT COUNT(*) FROM memory_episodes WHERE session_id IS NULL OR session_id=?", (scope,))
            deleted_episodes = int(count[0][0]) if count else 0
            self._q("DELETE FROM memory_episodes WHERE session_id IS NULL OR session_id=?", (scope,))
            self._q("DELETE FROM memory_working WHERE session_id=?", (scope,))
        return {"deleted_memory_items": deleted_items, "deleted_episodes": deleted_episodes, "scope": scope}

    def forget(self, key: str, *, scope: str = "global", kind: str | None = None, reason: str = "user_forget") -> int:
        where = ["status='active'", "key=?", "(scope=? OR scope='global')"]
        params: list = [key, scope]
        if kind:
            where.append("kind=?")
            params.append(kind)
        rows = self._q("SELECT id FROM memory_items WHERE " + " AND ".join(where), params)
        count = 0
        for (mid,) in rows:
            count += 1 if self.forget_memory(mid, reason=reason) else 0
        # Keep the original facts API consistent.
        if kind in (None, "fact"):
            self.delete_fact(key)
        return count

    def profile(self, *, scope: str = "global", limit: int = 50) -> list[dict]:
        # Profile is durable semantic memory only; raw notes, procedures and episodes are separate lanes.
        rows = self.list_memories(scope=scope, limit=max(limit * 2, 50), include_archived=False)
        return [row for row in rows if row["kind"] in {"fact", "preference", "goal", "profile"}][:max(1, int(limit))]


    def add_episode(self, user_text: str, assistant_text: str = "", *, outcome: str | None = None,
                    summary: str | None = None, session_id: str | None = None, run_id: str | None = None,
                    metadata: dict | None = None) -> int:
        if not str(user_text).strip():
            raise ValueError("episode user_text is empty")
        from app.knowledge.memory_extraction import redact_secrets
        safe_user = redact_secrets(user_text.strip())
        safe_assistant = redact_secrets(str(assistant_text or "").strip())
        safe_summary = redact_secrets(str(summary or "").strip()) or None
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute("INSERT INTO memory_episodes(session_id,run_id,user_text,assistant_text,outcome,summary,ts,metadata) VALUES(?,?,?,?,?,?,?,?)",
                                   (session_id, run_id, safe_user, safe_assistant, outcome, safe_summary, _now(),
                                    json.dumps(metadata or {}, ensure_ascii=False, default=str)))
                return int(cur.lastrowid)
        finally:
            conn.close()

    def recent_episodes(self, session_id: str | None = None, limit: int = 12) -> list[dict]:
        if session_id:
            rows = self._q("SELECT id,session_id,run_id,user_text,assistant_text,outcome,summary,ts,metadata FROM memory_episodes WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, int(limit)))
        else:
            rows = self._q("SELECT id,session_id,run_id,user_text,assistant_text,outcome,summary,ts,metadata FROM memory_episodes ORDER BY id DESC LIMIT ?", (int(limit),))
        out = []
        for r in rows:
            try: md = json.loads(r[8]) if r[8] else {}
            except Exception: md = {}
            out.append({"id": r[0], "session_id": r[1], "run_id": r[2], "user_text": r[3], "assistant_text": r[4],
                        "outcome": r[5], "summary": r[6], "ts": r[7], "metadata": md})
        return out

    def session_summary(self, session_id: str | None = None, *, limit: int = 20) -> dict:
        episodes = self.recent_episodes(session_id=session_id, limit=max(1, int(limit)))
        from collections import Counter
        counter = Counter()
        for episode in reversed(episodes):
            counter.update(t for t in _tokens((episode.get("user_text") or "") + " " + (episode.get("summary") or ""))
                            if len(t) > 2)
        stop = {"the", "and", "that", "this", "with", "from", "about", "you", "what", "does", "have",
                "من", "في", "على", "عن", "هذا", "هذه", "انا", "أنا", "هو", "هي"}
        topics = [token for token, _ in counter.most_common(10) if token not in stop][:6]
        return {
            "session_id": session_id,
            "episode_count": len(episodes),
            "topics": topics,
            "latest": episodes[0] if episodes else None,
            "recent": episodes[:min(5, len(episodes))],
        }

    def restore_memory(self, payload: dict, *, scope_override: str | None = None,
                       include_episodes: bool = False) -> dict:
        if not isinstance(payload, dict) or payload.get("schema") != "personal-agent.memory.v1":
            raise ValueError("unsupported memory export schema")
        imported_items = 0
        skipped_items = 0
        for row in payload.get("items", []):
            if row.get("status") != "active":
                continue
            try:
                target_scope = scope_override or row.get("scope") or "global"
                self.remember(row.get("value", ""), kind=row.get("kind", "fact"), key=row.get("key"),
                              scope=target_scope, source="import", confidence=float(row.get("confidence", 0.8)),
                              importance=int(row.get("importance", 3)), sensitivity="normal",
                              valid_at=row.get("valid_at"), invalid_at=row.get("invalid_at"),
                              expires_at=row.get("expires_at"), metadata=dict(row.get("metadata") or {}),
                              reason="memory_import")
                imported_items += 1
            except (TypeError, ValueError, KeyError):
                skipped_items += 1
        imported_episodes = 0
        if include_episodes:
            for episode in payload.get("episodes", []):
                try:
                    self.add_episode(episode.get("user_text", ""), episode.get("assistant_text", ""),
                                     outcome=episode.get("outcome"), summary=episode.get("summary"),
                                     session_id=episode.get("session_id"), run_id=episode.get("run_id"),
                                     metadata=episode.get("metadata") or {})
                    imported_episodes += 1
                except ValueError:
                    skipped_items += 1
        return {"imported_items": imported_items, "imported_episodes": imported_episodes, "skipped": skipped_items}

    def working_put(self, session_id: str, content: str, *, kind: str = "context", priority: int = 3,
                    expires_at: str | None = None, metadata: dict | None = None) -> int:
        now = _now()
        cur = self._connect()
        try:
            with cur:
                row = cur.execute("INSERT INTO memory_working(session_id,kind,content,priority,created_at,updated_at,expires_at,metadata) VALUES(?,?,?,?,?,?,?,?)",
                                  (session_id, kind, content, max(1, min(5, int(priority))), now, now, expires_at,
                                   json.dumps(metadata or {}, ensure_ascii=False, default=str)))
                return int(row.lastrowid)
        finally:
            cur.close()

    def working_recall(self, session_id: str, limit: int = 12) -> list[dict]:
        now = _now()
        rows = self._q("SELECT id,kind,content,priority,created_at,updated_at,expires_at,metadata FROM memory_working WHERE session_id=? AND (expires_at IS NULL OR expires_at>=?) ORDER BY priority DESC,updated_at DESC LIMIT ?",
                        (session_id, now, int(limit)))
        out=[]
        for r in rows:
            try: md=json.loads(r[7]) if r[7] else {}
            except Exception: md={}
            out.append({"id":r[0],"kind":r[1],"content":r[2],"priority":r[3],"created_at":r[4],"updated_at":r[5],"expires_at":r[6],"metadata":md})
        return out

    def working_clear(self, session_id: str) -> int:
        rows = self._q("SELECT COUNT(*) FROM memory_working WHERE session_id=?", (session_id,))
        count = int(rows[0][0]) if rows else 0
        self._q("DELETE FROM memory_working WHERE session_id=?", (session_id,))
        return count

    def upsert_entity(self, name: str, *, label: str = "entity", scope: str = "global", aliases=()) -> int:
        canonical = " ".join(_tokens(name)) or str(name).strip().lower()
        now = _now()
        conn = self._connect()
        try:
            with conn:
                row = conn.execute("SELECT id,aliases FROM memory_entities WHERE canonical=? AND scope=?", (canonical, scope)).fetchone()
                if row:
                    existing = json.loads(row[1]) if row[1] else []
                    merged = list(dict.fromkeys(existing + [str(a).strip() for a in aliases if str(a).strip()]))
                    conn.execute("UPDATE memory_entities SET label=?,aliases=?,updated_at=? WHERE id=?", (label, json.dumps(merged, ensure_ascii=False), now, row[0]))
                    return int(row[0])
                cur=conn.execute("INSERT INTO memory_entities(canonical,label,scope,aliases,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                                 (canonical,label,scope,json.dumps(list(aliases),ensure_ascii=False),now,now))
                return int(cur.lastrowid)
        finally:
            conn.close()

    def relate(self, subject: str, predicate: str, object_value: str, *, scope: str = "global",
               confidence: float = 1.0, source_memory_id: int | None = None,
               valid_at: str | None = None, invalid_at: str | None = None, metadata: dict | None = None) -> int:
        subject_id = self.upsert_entity(subject, scope=scope)
        now = _now()
        conn = self._connect()
        try:
            with conn:
                old = conn.execute("SELECT id FROM memory_relations WHERE subject_id=? AND predicate=? AND object_value=? AND scope=? AND status='active' LIMIT 1",
                                   (subject_id,predicate,object_value,scope)).fetchone()
                if old:
                    conn.execute("UPDATE memory_relations SET confidence=?,updated_at=?,valid_at=?,invalid_at=?,source_memory_id=?,metadata=? WHERE id=?",
                                 (max(0.0,min(1.0,float(confidence))),now,valid_at,invalid_at,source_memory_id,json.dumps(metadata or {},ensure_ascii=False,default=str),old[0]))
                    return int(old[0])
                cur=conn.execute("INSERT INTO memory_relations(subject_id,predicate,object_value,scope,confidence,status,valid_at,invalid_at,source_memory_id,created_at,updated_at,metadata) VALUES(?,?,?,?,?,'active',?,?,?,?,?,?)",
                                 (subject_id,predicate,object_value,scope,max(0.0,min(1.0,float(confidence))),valid_at,invalid_at,source_memory_id,now,now,json.dumps(metadata or {},ensure_ascii=False,default=str)))
                return int(cur.lastrowid)
        finally:
            conn.close()

    def graph(self, subject: str, *, scope: str = "global", limit: int = 20) -> list[dict]:
        canonical = " ".join(_tokens(subject)) or subject.strip().lower()
        now = _now()
        rows = self._q("SELECT e.canonical,r.predicate,r.object_value,r.confidence,r.valid_at,r.invalid_at,r.source_memory_id,r.metadata FROM memory_relations r JOIN memory_entities e ON e.id=r.subject_id WHERE e.canonical=? AND e.scope=? AND r.status='active' AND (r.valid_at IS NULL OR r.valid_at <= ?) AND (r.invalid_at IS NULL OR r.invalid_at > ?) ORDER BY r.confidence DESC,r.updated_at DESC LIMIT ?",
                        (canonical,scope,now,now,int(limit)))
        out=[]
        for r in rows:
            try: md=json.loads(r[7]) if r[7] else {}
            except Exception: md={}
            out.append({"subject":r[0],"predicate":r[1],"object":r[2],"confidence":r[3],"valid_at":r[4],"invalid_at":r[5],"source_memory_id":r[6],"metadata":md})
        return out

    def observe(self, user_text: str, *, assistant_text: str = "", outcome: str | None = None,
                session_id: str | None = None, run_id: str | None = None, metadata: dict | None = None) -> dict:
        """Record an episode and promote only high-confidence explicit facts/preferences."""
        episode_id = self.add_episode(user_text, assistant_text, outcome=outcome, session_id=session_id, run_id=run_id, metadata=metadata)
        candidates = extract_memory_candidates(user_text)
        promoted=[]
        for c in candidates:
            try:
                mid=self.add_memory_candidate(c, session_id=session_id, run_id=run_id, source_ref=f"episode:{episode_id}", scope="global", reason="explicit_statement")
                promoted.append({"id":mid,"kind":c.kind,"key":c.key,"value":c.value,"confidence":c.confidence})
            except ValueError:
                continue
        procedural = None
        if outcome == "completed":
            try:
                procedural = self._learn_procedure_from_successes(user_text, scope="global")
            except Exception:
                procedural = None
        if session_id:
            self.working_put(session_id, user_text, kind="recent_user_turn", priority=2, metadata={"episode_id": episode_id})
        return {"episode_id": episode_id, "promoted": promoted, "procedural": procedural}

    def _completed_procedure_evidence(self, goal_key: str, limit: int = 500) -> list[dict]:
        rows = self._q("SELECT run_id,metadata,ts FROM memory_episodes WHERE outcome='completed' ORDER BY id DESC LIMIT ?", (int(limit),))
        out = []
        for run_id, metadata, ts in rows:
            try:
                md = json.loads(metadata) if metadata else {}
            except Exception:
                md = {}
            if md.get("goal_key") == goal_key and md.get("plan_steps"):
                out.append({"run_id": run_id, "plan_steps": list(md.get("plan_steps") or []), "ts": ts})
        return out

    def _learn_procedure_from_successes(self, goal: str, *, scope: str = "global") -> dict | None:
        goal_key = normalize(goal)
        evidence = self._completed_procedure_evidence(goal_key)
        if len(evidence) < 2:
            return None
        sequences = [tuple(e["plan_steps"]) for e in evidence if e["plan_steps"]]
        if not sequences:
            return None
        counts = defaultdict(int)
        for seq in sequences:
            counts[seq] += 1
        seq, count = max(counts.items(), key=lambda item: (item[1], len(item[0])))
        if count < 2:
            return None
        # Do not turn trivial one-step retrievals into procedural memory. Those calls
        # are better represented by semantic memory and repeated query experience;
        # procedural memory is reserved for a workflow with at least two actions.
        if len(seq) < 2:
            return None
        value = " -> ".join(seq)
        mid = self.remember(value, kind="procedural", key=goal_key, scope=scope, source="auto",
                            confidence=min(0.96, 0.72 + 0.05 * min(count - 2, 5)), importance=3,
                            metadata={"tool_sequence": list(seq), "evidence_runs": [e["run_id"] for e in evidence[:10]],
                                      "success_count": count},
                            reason="repeated_successful_workflow")
        return {"id": mid, "goal_key": goal_key, "tool_sequence": list(seq), "evidence_count": count}

    def procedural_memory(self, query: str, *, top_k: int = 5, scope: str = "global") -> list[dict]:
        return self.search_memory(query, top_k=top_k, kinds={"procedural"}, scope=scope)

    def memory_health(self, *, scope: str = "global") -> dict:
        now = _now()
        active = self._q("SELECT kind,COUNT(*) FROM memory_items WHERE status='active' AND (scope=? OR scope='global') GROUP BY kind", (scope,))
        expiring = self._q("SELECT COUNT(*) FROM memory_items WHERE status='active' AND expires_at IS NOT NULL AND expires_at > ? AND expires_at <= datetime(?, '+30 days') AND (scope=? OR scope='global')", (now, now, scope))
        invalid = self._q("SELECT COUNT(*) FROM memory_items WHERE status='active' AND invalid_at IS NOT NULL AND invalid_at <= ? AND (scope=? OR scope='global')", (now, scope))
        history = self._q("SELECT COUNT(*) FROM memory_history")[0][0]
        return {"scope": scope, "active_by_kind": {k: int(c) for k, c in active},
                "expiring_within_30_days": int(expiring[0][0]) if expiring else 0,
                "invalid_still_active": int(invalid[0][0]) if invalid else 0,
                "history_events": int(history),
                "ok": int(invalid[0][0]) == 0 if invalid else True}

    def export_memory(self, *, scope: str = "global", include_history: bool = True, include_episodes: bool = True) -> dict:
        payload = {"schema": "personal-agent.memory.v1", "exported_at": _now(), "scope": scope,
                   "items": self.list_memories(scope=scope, limit=100000, include_archived=True),
                   "entities": [], "relations": []}
        payload["entities"] = [
            {"id": r[0], "canonical": r[1], "label": r[2], "scope": r[3], "aliases": json.loads(r[4]) if r[4] else []}
            for r in self._q("SELECT id,canonical,label,scope,aliases FROM memory_entities WHERE scope=? OR scope='global'", (scope,))
        ]
        payload["relations"] = [
            {"subject_id": r[0], "predicate": r[1], "object_value": r[2], "scope": r[3], "confidence": r[4],
             "status": r[5], "valid_at": r[6], "invalid_at": r[7], "source_memory_id": r[8]}
            for r in self._q("SELECT subject_id,predicate,object_value,scope,confidence,status,valid_at,invalid_at,source_memory_id FROM memory_relations WHERE scope=? OR scope='global'", (scope,))
        ]
        if include_history:
            payload["history"] = self.memory_history(scope=scope, limit=100000)
        if include_episodes:
            payload["episodes"] = self.recent_episodes(limit=100000)
        return payload

    def consolidate(self, *, scope: str = "global") -> dict:
        """Reconcile duplicate active memories and mark expired items inactive.

        Raw episodes and memory_history remain the source of truth; consolidation never
        destroys evidence. This is intentionally deterministic and replayable.
        """
        now = _now()
        duplicate_groups = 0
        archived = 0
        rows = self._q("SELECT id,kind,key,value,scope,confidence,importance,access_count FROM memory_items WHERE status='active' AND (scope=? OR scope='global') ORDER BY kind,key,revision DESC,id DESC", (scope,))
        seen = {}
        for row in rows:
            ident=(row[1],row[2],row[4]," ".join(_tokens(row[3])))
            if ident in seen:
                self._q("UPDATE memory_items SET status='superseded',invalid_at=?,updated_at=? WHERE id=?",(now,now,row[0]))
                duplicate_groups += 1
            else:
                seen[ident]=row[0]
        expired = self._q("SELECT id FROM memory_items WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ?", (now,))
        for (mid,) in expired:
            self._q("UPDATE memory_items SET status='expired',updated_at=? WHERE id=?", (now,mid))
            archived += 1
        # Staleness is a retention signal, not a correctness signal. Never auto-archive
        # current user facts/preferences; use it only for low-importance notes/procedures.
        stale_rows = self._q("SELECT id,updated_at,importance,access_count,confidence,kind FROM memory_items WHERE status='active' AND kind IN ('note','procedural') AND (scope=? OR scope='global')", (scope,))
        for mid, ts, importance, access_count, confidence, kind in stale_rows:
            try:
                age_days = max(0.0, (time.time() - time.mktime(time.strptime(ts, '%Y-%m-%dT%H:%M:%S'))) / 86400.0)
            except Exception:
                continue
            decay = math.exp(-age_days / 180.0)
            retention = (0.38 * decay) + (0.24 * float(confidence)) + (0.20 * (int(importance) / 5.0)) + (0.18 * min(int(access_count), 10) / 10.0)
            if retention < 0.22 and int(importance) <= 2 and int(access_count) == 0:
                self._q("UPDATE memory_items SET status='archived',updated_at=? WHERE id=?", (now, mid))
                archived += 1
        return {"duplicates_reconciled": duplicate_groups, "expired": archived, "active": len(self.list_memories(scope=scope, limit=100000))}

    def cleanup(self, *, scope: str = "global", archive_after_days: int = 365, min_importance: int = 2) -> dict:
        now = _now()
        # Expiry is semantic; archive is retention policy. Neither deletes history.
        expired_rows=self._q("SELECT id FROM memory_items WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ? AND (scope=? OR scope='global')",(now,scope))
        for mid, in expired_rows:
            self._q("UPDATE memory_items SET status='expired',updated_at=? WHERE id=?",(now,mid))
        cutoff=time.time()-archive_after_days*86400
        archived=0
        rows=self._q("SELECT id,updated_at,importance,access_count FROM memory_items WHERE status='active' AND (scope=? OR scope='global')",(scope,))
        for mid, ts, importance, accesses in rows:
            try: age=time.time()-time.mktime(time.strptime(ts,'%Y-%m-%dT%H:%M:%S'))
            except Exception: continue
            if age > 86400*archive_after_days and int(importance) <= min_importance and int(accesses) == 0:
                self._q("UPDATE memory_items SET status='archived',updated_at=? WHERE id=?",(now,mid)); archived+=1
        return {"expired":len(expired_rows),"archived":archived}

    def memory_stats(self) -> dict:
        rows=self._q("SELECT kind,status,COUNT(*) FROM memory_items GROUP BY kind,status")
        stats=defaultdict(int)
        for kind,status,count in rows:
            stats[f"{kind}:{status}"]=int(count)
        episodes=self._q("SELECT COUNT(*) FROM memory_episodes")[0][0]
        relations=self._q("SELECT COUNT(*) FROM memory_relations WHERE status='active'")[0][0]
        return {"items":dict(stats),"episodes":int(episodes),"active_relations":int(relations)}

    # --- Deterministic experience store ---
    def cache_plan(self, goal_key: str, plan: dict, actual_cost: float, actual_duration: float):
        existing = self._q("SELECT success_count,avg_cost,avg_duration FROM plan_cache WHERE goal_key=?", (goal_key,))
        if existing:
            n, old_cost, old_dur = existing[0]
            n2 = n + 1
            cost = (old_cost * n + actual_cost) / n2
            dur = (old_dur * n + actual_duration) / n2
            failures = int(self._q("SELECT failure_count FROM plan_cache WHERE goal_key=?", (goal_key,))[0][0])
        else:
            n2, cost, dur, failures = 1, actual_cost, actual_duration, 0
        self._q("INSERT OR REPLACE INTO plan_cache(goal_key,plan,success_count,failure_count,avg_cost,avg_duration,last_used) VALUES(?,?,?,?,?,?,?)",
                (goal_key, json.dumps(plan, ensure_ascii=False, default=str), n2, failures, cost, dur, _now()))

    def record_plan_failure(self, goal_key: str):
        self._q("UPDATE plan_cache SET failure_count=failure_count+1,last_used=? WHERE goal_key=?", (_now(), goal_key))

    def cached_plan(self, goal_key: str) -> dict | None:
        rows = self._q("SELECT plan,success_count,failure_count,avg_cost,avg_duration,last_used FROM plan_cache WHERE goal_key=?", (goal_key,))
        if not rows:
            return None
        plan, success, failure, avg_cost, avg_duration, last_used = rows[0]
        try:
            return {"plan": json.loads(plan), "success_count": success, "failure_count": failure,
                    "avg_cost": avg_cost, "avg_duration": avg_duration, "last_used": last_used}
        except Exception:
            return None

    def effects_for_all_runs(self) -> list[dict]:
        rows = self._q("SELECT run_id, step_id, attempt, tool, args, output, ok, verified, error, duration_ms, ts, state_before, state_after FROM effects ORDER BY id")
        return [{"run_id": run_id, "step_id": step_id, "attempt": attempt, "tool": tool,
                 "args": json.loads(args), "output": json.loads(output) if output else None,
                 "ok": bool(ok), "verified": bool(verified), "error": error,
                 "duration_ms": duration_ms, "ts": ts, "state_before": state_before, "state_after": state_after}
                for run_id, step_id, attempt, tool, args, output, ok, verified, error, duration_ms, ts, state_before, state_after in rows]

    def last_completed_turn_meta(self, session_id: str | None = None) -> dict | None:
        """Return metadata for the latest completed conversational turn.

        This is intentionally broader than ``last_completed_output``: informational
        turns such as ``recall_fact`` may not be a meaningful result, but they can
        still establish the semantic target used by a later correction (e.g.
        "what is my city?" -> "No, I mean Cairo").
        """
        if session_id:
            rows = self._q(
                "SELECT run_id,goal,plan,final_message,updated_at FROM runtime_runs "
                "WHERE status='completed' AND session_id=? "
                "ORDER BY updated_at DESC, rowid DESC LIMIT 1",
                (session_id,),
            )
        else:
            rows = self._q(
                "SELECT run_id,goal,plan,final_message,updated_at FROM runtime_runs "
                "WHERE status='completed' ORDER BY updated_at DESC, rowid DESC LIMIT 1"
            )
        if not rows:
            return None
        run_id, goal, plan_json, final_message, updated_at = rows[0]
        try:
            plan = json.loads(plan_json) if plan_json else {}
        except Exception:
            plan = {}
        return {
            "run_id": run_id,
            "goal": goal,
            "plan": plan,
            "final_message": final_message,
            "updated_at": updated_at,
        }

    def last_completed_output(self, session_id: str | None = None) -> dict | None:
        """Return the latest meaningful tool output, not memory bookkeeping output.

        A user asking "what was the last result?" should not make the answer to that
        question become the next "last result". Likewise, a `remember_result` action
        is persistence bookkeeping; the producer action before it is the meaningful result.
        """
        if session_id:
            rows = self._q("SELECT run_id,goal,plan,final_message,updated_at FROM runtime_runs WHERE status='completed' AND session_id=? ORDER BY updated_at DESC, rowid DESC LIMIT 50", (session_id,))
        else:
            rows = self._q("SELECT run_id,goal,plan,final_message,updated_at FROM runtime_runs WHERE status='completed' ORDER BY updated_at DESC, rowid DESC LIMIT 50")
        ignored_tools = {
            "recall_last_result", "remember_last_result", "remember_result", "save_note",
            "remember_fact", "remember_memory", "recall_fact", "search_memory", "memory_profile",
            "memory_stats", "memory_health", "memory_history", "memory_graph", "recent_runs",
            "learning_status", "experience", "analytics", "world", "seed",
        }
        for run_id, goal, plan_json, final_message, updated_at in rows:
            try:
                plan = json.loads(plan_json) if plan_json else {}
            except Exception:
                plan = {}
            steps = list(plan.get("steps") or [])
            for step in reversed(steps):
                if (step.get("status") == "done"
                        and step.get("output") is not None
                        and step.get("tool") not in ignored_tools):
                    return {"run_id": run_id, "goal": goal, "output": step.get("output"),
                            "tool": step.get("tool"), "step_id": step.get("id"),
                            "args": dict(step.get("args") or {}), "plan": plan,
                            "final_message": final_message, "updated_at": updated_at}
        return None


    def completed_runtime_runs(self, session_id: str | None = None) -> list[dict]:
        if session_id:
            rows = self._q("SELECT run_id,status,goal,started_at,updated_at,session_id FROM runtime_runs WHERE session_id=? ORDER BY started_at", (session_id,))
        else:
            rows = self._q("SELECT run_id,status,goal,started_at,updated_at,session_id FROM runtime_runs ORDER BY started_at")
        return [{"run_id": run_id, "status": status, "goal": goal, "started_at": started_at, "updated_at": updated_at, "session_id": sid}
                for run_id, status, goal, started_at, updated_at, sid in rows]

    def plan_cache_stats(self) -> list[dict]:
        rows = self._q("SELECT goal_key,success_count,failure_count,avg_cost,avg_duration,last_used FROM plan_cache ORDER BY last_used DESC")
        return [{"goal_key": k, "success_count": s, "failure_count": f, "avg_cost": c,
                 "avg_duration": d, "last_used": last} for k, s, f, c, d, last in rows]


_default: Memory | None = None


def configure(path) -> Memory:
    global _default
    _default = Memory(path)
    return _default


def get_memory() -> Memory:
    global _default
    # Canonical Brain executions inject their Memory authority through a contextvar so
    # every memory tool uses the exact same store instance as semantic retrieval and Brain state.
    try:
        from app.runtime.memory_context import current_memory
        contextual = current_memory()
        if contextual is not None:
            return contextual
    except Exception:
        pass
    if _default is None:
        _default = Memory(DEFAULT_PATH)
    return _default

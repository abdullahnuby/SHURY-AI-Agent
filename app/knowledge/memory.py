"""Durable local memory, experience, checkpoints and append-only effects.

No embeddings or remote model are required. Retrieval uses deterministic BM25-like
lexical ranking plus freshness/importance boosts. SQLite is WAL-backed for crash
resilience and concurrent short-lived connections.
"""
import hashlib
import os
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
from app.knowledge.memory_schema import (
    CANONICAL_MEMORY_SCHEMA_NAME, CANONICAL_MEMORY_SCHEMA_VERSION,
    validate_memory_record_mapping,
)
from app.knowledge.memory_types import (
    GLOBAL_SYSTEM, KNOWLEDGE, COMPANY, USER, SESSION, RUN, MEMORY_SCOPES, LEGACY_SCOPE_ALIASES,
    CANONICAL_MEMORY_TYPES, validate_memory_type_operation, normalize_memory_type,
    ENTITY, RELATION,
)
from app.intelligence.understanding import normalize
from app.knowledge.memory_retrieval import search as hybrid_search
from app.knowledge.temporal_memory import project
from app.knowledge.episodic_memory import canonical_episode_payload, sanitize_entities, sanitize_tool_events, sanitize_metadata, score_episode

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "memory.db"

DEFAULT_OWNER_ID = os.getenv("SHURY_MEMORY_OWNER_ID", "local-default")
LAST_RESULT_IGNORED_TOOLS = frozenset({
    "recall_last_result", "remember_last_result", "remember_result", "save_note",
    "remember_fact", "remember_memory", "recall_fact", "search_memory", "memory_profile",
    "memory_stats", "memory_health", "memory_history", "memory_graph", "recent_runs",
    "learning_status", "experience", "analytics", "world", "seed",
})

LEGACY_MIGRATION_SCHEMA_NAME = "personal-agent.memory-legacy-migration"
LEGACY_MIGRATION_SCHEMA_VERSION = 1
LEGACY_UNRESOLVED_STATUS = "unresolved"

# Phase 1: the Memory class is the single canonical memory authority.
# Other memory entry points are compatibility wrappers around this authority.
CANONICAL_MEMORY_API = (
    "remember",
    "retrieve",
    "update",
    "correct",
    "forget",
    "record_episode",
    "record_working_context",
    "link_entity",
    "link_relation",
    "consolidate",
    "export",
    "health",
)

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
    goal_key TEXT NOT NULL,
    owner_id TEXT,
    plan TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    avg_cost REAL NOT NULL DEFAULT 0,
    avg_duration REAL NOT NULL DEFAULT 0,
    last_used TEXT NOT NULL,
    PRIMARY KEY(goal_key, owner_id)
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
CREATE TABLE IF NOT EXISTS memory_schema_meta (
    schema_name TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT,
    value TEXT NOT NULL,
    normalized TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'user',
    owner_id TEXT,
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
    UNIQUE(kind, key, scope, owner_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_memory_items_lookup ON memory_items(status, scope, owner_id, kind);
CREATE INDEX IF NOT EXISTS idx_memory_items_key ON memory_items(key, scope, owner_id, status);
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
    ts TEXT NOT NULL,
    owner_id TEXT,
    scope TEXT,
    session_id TEXT,
    run_id TEXT,
    status TEXT
);
CREATE INDEX IF NOT EXISTS idx_memory_history_memory ON memory_history(memory_id, id);
CREATE TABLE IF NOT EXISTS memory_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id TEXT,
    session_id TEXT,
    run_id TEXT,
    user_text TEXT NOT NULL,
    assistant_text TEXT,
    outcome TEXT,
    summary TEXT,
    ts TEXT NOT NULL,
    tool_events TEXT NOT NULL DEFAULT '[]',
    entities TEXT NOT NULL DEFAULT '[]',
    experience_kind TEXT NOT NULL DEFAULT 'interaction',
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memory_episodes_owner_session ON memory_episodes(owner_id, session_id, id);
CREATE INDEX IF NOT EXISTS idx_memory_episodes_run ON memory_episodes(run_id, id);
CREATE TABLE IF NOT EXISTS memory_working (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'context',
    content TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memory_working_session ON memory_working(owner_id, session_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS memory_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'entity',
    scope TEXT NOT NULL DEFAULT 'user',
    owner_id TEXT,
    session_id TEXT,
    run_id TEXT,
    aliases TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(canonical, scope, owner_id, session_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_entities_lookup ON memory_entities(canonical, scope, owner_id, session_id, run_id);
CREATE TABLE IF NOT EXISTS memory_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    predicate TEXT NOT NULL,
    object_value TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'user',
    owner_id TEXT,
    session_id TEXT,
    run_id TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    valid_at TEXT,
    invalid_at TEXT,
    source_memory_id INTEGER,
    revision INTEGER NOT NULL DEFAULT 1,
    supersedes_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memory_relations_subject ON memory_relations(subject_id, scope, owner_id, session_id, run_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_relations_object ON memory_relations(object_value, scope, owner_id, session_id, run_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_relations_predicate ON memory_relations(subject_id, predicate, scope, owner_id, session_id, run_id, status);
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

    def __init__(self, path, *, owner_id: str | None = None):
        self.path = Path(path)
        self.default_owner_id = str(owner_id or DEFAULT_OWNER_ID)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            with conn:
                conn.executescript(SCHEMA)
                self._migrate(conn)
                # Upgrade legacy advanced tables before creating Phase 2 indexes.
                self._migrate_ownership(conn)
                self._migrate_graph_v7(conn)
                conn.executescript(ADVANCED_SCHEMA)
                self._migrate_ownership(conn)
                self._sanitize_legacy_placeholders(conn)
                self._migrate_schema_v3(conn)
                self._migrate_graph_v7(conn)
                self._migrate_schema_v8(conn)
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
        plan_cols = {r[1] for r in conn.execute("PRAGMA table_info(plan_cache)")}
        plan_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='plan_cache'").fetchone()
        plan_pk = {r[1] for r in conn.execute("PRAGMA table_info(plan_cache)") if int(r[5] or 0) > 0}
        if "owner_id" not in plan_cols or len(plan_pk) < 2:
            conn.execute("ALTER TABLE plan_cache RENAME TO plan_cache_phase2_legacy")
            conn.execute("""CREATE TABLE plan_cache (
                goal_key TEXT NOT NULL, owner_id TEXT, plan TEXT NOT NULL,
                success_count INTEGER NOT NULL DEFAULT 0, failure_count INTEGER NOT NULL DEFAULT 0,
                avg_cost REAL NOT NULL DEFAULT 0, avg_duration REAL NOT NULL DEFAULT 0,
                last_used TEXT NOT NULL, PRIMARY KEY(goal_key, owner_id)
            )""")
            conn.execute("""INSERT INTO plan_cache(goal_key,owner_id,plan,success_count,failure_count,avg_cost,avg_duration,last_used)
                SELECT goal_key,NULL,plan,success_count,failure_count,avg_cost,avg_duration,last_used FROM plan_cache_phase2_legacy""")
            conn.execute("DROP TABLE plan_cache_phase2_legacy")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plan_cache_owner_goal ON plan_cache(owner_id, goal_key)")

    @staticmethod
    def _migrate_ownership(conn):
        """Add owner boundaries without assigning legacy rows to a user."""
        def exists(table: str) -> bool:
            return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

        if exists("memory_items"):
            cols={r[1] for r in conn.execute("PRAGMA table_info(memory_items)")}
            memory_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_items'").fetchone()
            if "owner_id" not in cols or "UNIQUE(kind,key,scope,owner_id,revision)" not in str((memory_sql or [""])[0]).replace(" ", ""):
                conn.execute("ALTER TABLE memory_items RENAME TO memory_items_phase2_legacy")
                conn.execute("""CREATE TABLE memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, key TEXT, value TEXT NOT NULL, normalized TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'user', owner_id TEXT, session_id TEXT, run_id TEXT, source TEXT NOT NULL DEFAULT 'user',
                    source_ref TEXT, confidence REAL NOT NULL DEFAULT 1.0, importance INTEGER NOT NULL DEFAULT 3, sensitivity TEXT NOT NULL DEFAULT 'normal',
                    status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, valid_at TEXT, invalid_at TEXT,
                    expires_at TEXT, last_accessed TEXT, access_count INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
                    supersedes_id INTEGER, metadata TEXT NOT NULL DEFAULT '{}', UNIQUE(kind,key,scope,owner_id,revision)
                )""")
                conn.execute("""INSERT INTO memory_items(id,kind,key,value,normalized,scope,owner_id,session_id,run_id,source,source_ref,confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,last_accessed,access_count,revision,supersedes_id,metadata)
                    SELECT id,kind,key,value,normalized,scope,NULL,session_id,run_id,source,source_ref,confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,last_accessed,access_count,revision,supersedes_id,metadata
                    FROM memory_items_phase2_legacy""")
                conn.execute("DROP TABLE memory_items_phase2_legacy")

        for table in ("memory_episodes","memory_working","memory_relations"):
            if not exists(table):
                continue
            cols={r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "owner_id" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN owner_id TEXT")

        if exists("memory_entities"):
            cols={r[1] for r in conn.execute("PRAGMA table_info(memory_entities)")}
            sql=conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_entities'").fetchone()
            definition = str((sql or [''])[0]).replace(" ", "")
            needs_rebuild = (
                "owner_id" not in cols
                or "session_id" not in cols
                or "run_id" not in cols
                or "UNIQUE(canonical,scope,owner_id,session_id,run_id)" not in definition
            )
            if needs_rebuild:
                conn.execute("ALTER TABLE memory_entities RENAME TO memory_entities_phase2_legacy")
                conn.execute("""CREATE TABLE memory_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, canonical TEXT NOT NULL, label TEXT NOT NULL DEFAULT 'entity',
                    scope TEXT NOT NULL DEFAULT 'user', owner_id TEXT, session_id TEXT, run_id TEXT,
                    aliases TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(canonical,scope,owner_id,session_id,run_id)
                )""")
                legacy_cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_entities_phase2_legacy)")}
                select_session = "session_id" if "session_id" in legacy_cols else "NULL"
                select_run = "run_id" if "run_id" in legacy_cols else "NULL"
                select_owner = "owner_id" if "owner_id" in legacy_cols else "NULL"
                conn.execute(
                    f"""INSERT INTO memory_entities(id,canonical,label,scope,owner_id,session_id,run_id,aliases,created_at,updated_at)
                    SELECT id,canonical,label,scope,{select_owner},{select_session},{select_run},aliases,created_at,updated_at
                    FROM memory_entities_phase2_legacy"""
                )
                conn.execute("DROP TABLE memory_entities_phase2_legacy")

        if exists("memory_items"):
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_lookup ON memory_items(status,scope,owner_id,kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_key ON memory_items(key,scope,owner_id,status)")
        if exists("memory_episodes"):
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_episodes_owner_session ON memory_episodes(owner_id,session_id,id)")
        if exists("memory_working"):
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_working_session ON memory_working(owner_id,session_id,updated_at DESC)")
        if exists("memory_entities"):
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_entities_lookup ON memory_entities(canonical,scope,owner_id)")
        if exists("memory_relations"):
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_relations_object ON memory_relations(object_value,scope,owner_id,status)")

    @staticmethod
    def _migrate_schema_v3(conn):
        """Register the canonical Phase 3 schema without rewriting legacy storage names."""
        columns = {r[1] for r in conn.execute("PRAGMA table_info(memory_history)")}
        for name, typ in (("owner_id", "TEXT"), ("scope", "TEXT"), ("session_id", "TEXT"), ("run_id", "TEXT"), ("status", "TEXT")):
            if name not in columns:
                conn.execute(f"ALTER TABLE memory_history ADD COLUMN {name} {typ}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_history_scope_owner ON memory_history(scope,owner_id,id)")
        now = _now()
        conn.execute(
            "INSERT INTO memory_schema_meta(schema_name,schema_version,applied_at) VALUES(?,?,?) "
            "ON CONFLICT(schema_name) DO UPDATE SET schema_version=excluded.schema_version,applied_at=excluded.applied_at",
            (CANONICAL_MEMORY_SCHEMA_NAME, CANONICAL_MEMORY_SCHEMA_VERSION, now),
        )

    @staticmethod
    def _migrate_schema_v8(conn):
        """Upgrade episodic storage with structured experience evidence."""
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_episodes'").fetchone() is None:
            return
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_episodes)")}
        for name, definition in (
            ("tool_events", "TEXT NOT NULL DEFAULT '[]'"),
            ("entities", "TEXT NOT NULL DEFAULT '[]'"),
            ("experience_kind", "TEXT NOT NULL DEFAULT 'interaction'"),
        ):
            if name not in columns:
                conn.execute(f"ALTER TABLE memory_episodes ADD COLUMN {name} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_episodes_owner_ts ON memory_episodes(owner_id,ts DESC,id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_episodes_owner_run ON memory_episodes(owner_id,run_id,id DESC)")

    @staticmethod
    def _migrate_graph_v7(conn):
        """Upgrade entity/relation storage for canonical identity and historical relations."""
        def exists(table: str) -> bool:
            return conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone() is not None

        if exists("memory_entities"):
            cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_entities)")}
            if "session_id" not in cols:
                conn.execute("ALTER TABLE memory_entities ADD COLUMN session_id TEXT")
            if "run_id" not in cols:
                conn.execute("ALTER TABLE memory_entities ADD COLUMN run_id TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_entities_context "
                "ON memory_entities(scope,owner_id,session_id,run_id,canonical)"
            )

        if exists("memory_relations"):
            cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_relations)")}
            for name, typ in (("session_id", "TEXT"), ("run_id", "TEXT"), ("revision", "INTEGER NOT NULL DEFAULT 1"), ("supersedes_id", "INTEGER")):
                if name not in cols:
                    conn.execute(f"ALTER TABLE memory_relations ADD COLUMN {name} {typ}")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_relations_context "
                "ON memory_relations(scope,owner_id,session_id,run_id,subject_id,predicate,status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_relations_revision "
                "ON memory_relations(supersedes_id,revision,id)"
            )

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
                "INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts,owner_id,scope,session_id,run_id,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, revision, "SANITIZE", value, None, "legacy_placeholder_cleanup", "system", now, None, None, None, None, "archived"),
            )
        conn.execute("UPDATE facts SET status='deleted',ts=? WHERE key='name' AND trim(value) IN ('?', '؟؟', '')", (now,))

    @staticmethod
    def _ensure_legacy_migration_schema(conn):
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS legacy_memory_migration_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            backup_path TEXT,
            source_counts TEXT NOT NULL DEFAULT '{}',
            migrated_counts TEXT NOT NULL DEFAULT '{}',
            unresolved_counts TEXT NOT NULL DEFAULT '{}',
            skipped_counts TEXT NOT NULL DEFAULT '{}',
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS legacy_memory_migration_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            source_table TEXT NOT NULL,
            source_id TEXT NOT NULL,
            classification TEXT NOT NULL,
            target_id INTEGER,
            target_kind TEXT,
            target_scope TEXT,
            target_owner_id TEXT,
            target_status TEXT,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(run_id, source_table, source_id)
        );
        CREATE INDEX IF NOT EXISTS idx_legacy_memory_migration_records_run
            ON legacy_memory_migration_records(run_id, source_table, decision);
        CREATE TABLE IF NOT EXISTS memory_migration_meta (
            schema_name TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            last_run_id INTEGER,
            applied_at TEXT NOT NULL,
            status TEXT NOT NULL
        );
        """)

    @staticmethod
    def _legacy_source_counts(conn) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in ("facts", "fact_history", "notes"):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if exists:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            else:
                counts[table] = 0
        counts["global_personal_memory_items"] = int(conn.execute(
            """SELECT COUNT(*) FROM memory_items
               WHERE owner_id IS NULL AND scope IN ('global','global_system')
                 AND source='user' AND kind IN ('fact','note')
                 AND status IN ('active','archived','deleted','unresolved')"""
        ).fetchone()[0])
        counts["legacy_backfilled_memory_items"] = int(conn.execute(
            """SELECT COUNT(*) FROM memory_items
               WHERE owner_id IS NULL
                 AND (json_extract(metadata,'$.legacy_fact') = 1
                      OR json_extract(metadata,'$.legacy_note_id') IS NOT NULL)"""
        ).fetchone()[0])
        return counts

    @staticmethod
    def _create_legacy_backup(source_path: Path, backup_path: Path | None = None) -> str | None:
        if not source_path.exists():
            return None
        if backup_path is None:
            backup_path = source_path.with_name(
                f"{source_path.name}.phase14-backup-{time.strftime('%Y%m%d-%H%M%S')}.sqlite"
            )
        backup_path = Path(backup_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(source_path)
        try:
            dst = sqlite3.connect(backup_path)
            try:
                src.backup(dst)
                dst.commit()
            finally:
                dst.close()
        finally:
            src.close()
        return str(backup_path)

    @staticmethod
    def _legacy_fact_history(conn, key: str):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fact_history'").fetchone():
            return []
        return conn.execute(
            "SELECT id,key,value,status,ts,source FROM fact_history WHERE key=? ORDER BY id",
            (key,),
        ).fetchall()

    def migrate_legacy_memory(self, *, backup_path: str | Path | None = None, dry_run: bool = False) -> dict:
        """Classify and migrate legacy personal memory without guessing ownership.

        Valid legacy facts/notes whose owner cannot be proven are imported as
        USER-scoped ``unresolved`` records with owner_id=NULL, so they can never
        enter live user retrieval until explicitly resolved. Invalid placeholders
        are skipped from promotion but remain represented in the migration audit.
        """
        db_path = self.path
        backup = self._create_legacy_backup(db_path, Path(backup_path) if backup_path else None) if not dry_run else None
        conn = self._connect()
        started = _now()
        try:
            self._ensure_legacy_migration_schema(conn)
            with conn:
                prior = conn.execute(
                    "SELECT id,status FROM legacy_memory_migration_runs ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if prior and prior[1] == "completed":
                    return self.legacy_migration_status(conn=conn, latest_only=True)
                source_counts = self._legacy_source_counts(conn)
                run_id = conn.execute(
                    "INSERT INTO legacy_memory_migration_runs(started_at,status,backup_path,source_counts) VALUES(?,?,?,?)",
                    (started, "dry_run" if dry_run else "running", backup or "", json.dumps(source_counts, ensure_ascii=False, sort_keys=True)),
                ).lastrowid
                migrated = defaultdict(int)
                unresolved = defaultdict(int)
                skipped = defaultdict(int)

                def record(source_table, source_id, classification, *, target_id=None, target_kind=None,
                           target_scope=None, target_owner_id=None, target_status=None,
                           decision="unresolved", reason="", metadata=None):
                    conn.execute(
                        """INSERT INTO legacy_memory_migration_records
                        (run_id,source_table,source_id,classification,target_id,target_kind,target_scope,target_owner_id,target_status,decision,reason,metadata,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (run_id, str(source_table), str(source_id), classification, target_id, target_kind, target_scope,
                         target_owner_id, target_status, decision, reason, json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True), _now()),
                    )

                if not dry_run:
                    fact_rows = conn.execute("SELECT key,value,ts,status,confidence,source,revision FROM facts ORDER BY key").fetchall() if source_counts["facts"] else []
                    for key, value, ts, status, confidence, source, revision in fact_rows:
                        placeholder = (not str(key or '').strip() or not str(value or '').strip() or str(value).strip() in {'?', '؟؟'})
                        if placeholder:
                            skipped["invalid_placeholder"] += 1
                            record("facts", key or "<missing>", "invalid_placeholder", target_kind="fact", target_scope="user",
                                   target_status="archived", decision="skipped", reason="legacy fact is empty or placeholder",
                                   metadata={"legacy_status": status, "source": source})
                            conn.execute("UPDATE facts SET status='migrated_placeholder' WHERE key=?", (key,))
                            continue
                        hist = self._legacy_fact_history(conn, key)
                        history_values = [(h[2], h[3], h[4], h[5]) for h in hist if h[2] is not None]
                        # Preserve every historical value in the canonical store, but do not claim ownership.
                        prior_target = None
                        history_revisions = max(0, int(revision) - 1)
                        if history_values:
                            if len(history_values) != history_revisions:
                                history_revisions = len(history_values)
                            for idx, (hvalue, hstatus, hts, hsource) in enumerate(history_values, start=1):
                                existing = conn.execute(
                                    "SELECT id FROM memory_items WHERE kind='fact' AND key=? AND scope='user' AND owner_id IS NULL AND revision=?",
                                    (self.canonical_key(key), idx),
                                ).fetchone()
                                if existing:
                                    prior_target = existing[0]
                                    continue
                                mid = conn.execute(
                                    """INSERT INTO memory_items(
                                        kind,key,value,normalized,scope,owner_id,session_id,run_id,source,source_ref,
                                        confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,last_accessed,
                                        access_count,revision,supersedes_id,metadata
                                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                    (
                                        "fact", self.canonical_key(key), str(hvalue),
                                        " ".join(_tokens(self.canonical_key(key)+" "+str(hvalue))),
                                        "user", None, None, None, hsource or source or "legacy",
                                        f"legacy:facts:{key}:fact_history", float(confidence or 1.0), 5, "normal",
                                        "archived" if hstatus in {"deleted","archived"} else LEGACY_UNRESOLVED_STATUS,
                                        hts or ts or _now(), hts or ts or _now(), None, None, None, None, 0, idx, prior_target,
                                        json.dumps({"legacy_fact_key": key, "legacy_fact_history_id": hist[idx-1][0], "owner_resolution": "unknown"}, ensure_ascii=False),
                                    )
                                ).lastrowid
                                prior_target = mid
                                record("fact_history", hist[idx-1][0], "legacy_fact_history", target_id=mid, target_kind="fact", target_scope="user",
                                       target_status=LEGACY_UNRESOLVED_STATUS if hstatus not in {"deleted","archived"} else "archived",
                                       decision="migrated", reason="preserved historical legacy fact revision", metadata={"key": key, "revision": idx})
                                migrated["fact_history"] += 1
                        current_revision = max(int(revision or 1), history_revisions + 1)
                        existing = conn.execute(
                            "SELECT id FROM memory_items WHERE kind='fact' AND key=? AND scope='user' AND owner_id IS NULL AND revision=?",
                            (self.canonical_key(key), current_revision),
                        ).fetchone()
                        if existing:
                            mid = existing[0]
                        else:
                            mid = conn.execute(
                                """INSERT INTO memory_items(
                                    kind,key,value,normalized,scope,owner_id,session_id,run_id,source,source_ref,
                                    confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,last_accessed,
                                    access_count,revision,supersedes_id,metadata
                                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    "fact", self.canonical_key(key), str(value),
                                    " ".join(_tokens(self.canonical_key(key)+" "+str(value))),
                                    "user", None, None, None, source or "legacy", f"legacy:facts:{key}",
                                    float(confidence or 1.0), 5, "normal",
                                    "archived" if status in {"deleted","archived"} else LEGACY_UNRESOLVED_STATUS,
                                    ts or _now(), ts or _now(), None, None, None, None, 0, current_revision, prior_target,
                                    json.dumps({"legacy_fact": 1, "legacy_fact_key": key, "owner_resolution": "unknown"}, ensure_ascii=False),
                                )
                            ).lastrowid
                        target_status = "archived" if status in {"deleted","archived"} else LEGACY_UNRESOLVED_STATUS
                        if target_status == LEGACY_UNRESOLVED_STATUS:
                            unresolved["fact"] += 1
                        else:
                            skipped["deleted_fact_preserved"] += 1
                        record("facts", key, "user_fact_owner_unknown", target_id=mid, target_kind="fact", target_scope="user",
                               target_status=target_status, decision="migrated", reason="legacy fact has no provable owner; never auto-assign default owner",
                               metadata={"revision": current_revision, "source": source, "legacy_status": status})
                        conn.execute("UPDATE facts SET status='migrated' WHERE key=?", (key,))

                    note_rows = conn.execute("SELECT id,text,ts,importance,tags,status,source,confidence FROM notes ORDER BY id") if source_counts["notes"] else []
                    for nid, text, ts, importance, tags, status, source, confidence in note_rows:
                        placeholder = not str(text or '').strip()
                        if placeholder:
                            skipped["invalid_placeholder"] += 1
                            record("notes", nid, "invalid_placeholder", target_kind="note", target_scope="user", target_status="archived",
                                   decision="skipped", reason="legacy note is empty", metadata={"source": source})
                            conn.execute("UPDATE notes SET status='migrated_placeholder' WHERE id=?", (nid,))
                            continue
                        existing = conn.execute(
                            "SELECT id FROM memory_items WHERE kind='note' AND scope='user' AND owner_id IS NULL AND json_extract(metadata,'$.legacy_note_id')=?",
                            (nid,),
                        ).fetchone()
                        if existing:
                            mid = existing[0]
                        else:
                            mid = conn.execute(
                                """INSERT INTO memory_items(
                                    kind,key,value,normalized,scope,owner_id,session_id,run_id,source,source_ref,
                                    confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,last_accessed,
                                    access_count,revision,supersedes_id,metadata
                                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    "note", None, str(text), " ".join(_tokens(str(text))), "user", None, None, None,
                                    source or "legacy", f"legacy:notes:{nid}", float(confidence or 1.0), int(importance or 3), "normal",
                                    LEGACY_UNRESOLVED_STATUS, ts or _now(), ts or _now(), None, None, None, None, 0, 1, None,
                                    json.dumps({"legacy_note_id": nid, "tags": tags, "owner_resolution": "unknown"}, ensure_ascii=False),
                                )
                            ).lastrowid
                        unresolved["note"] += 1
                        record("notes", nid, "user_note_owner_unknown", target_id=mid, target_kind="note", target_scope="user",
                               target_status=LEGACY_UNRESOLVED_STATUS, decision="migrated", reason="legacy note has no provable owner; never auto-assign default owner",
                               metadata={"source": source, "tags": tags, "legacy_status": status})
                        conn.execute("UPDATE notes SET status='migrated' WHERE id=?", (nid,))

                    # Quarantine legacy backfills/global personal rows already copied by earlier versions.
                    rows = conn.execute(
                        """SELECT id,kind,key,value,scope,owner_id,status,metadata FROM memory_items
                           WHERE owner_id IS NULL AND source='user' AND kind IN ('fact','note')
                             AND scope IN ('global','global_system')
                             AND status IN ('active','archived','deleted','unresolved')"""
                    ).fetchall()
                    for mid, kind, key, value, scope, owner, status, metadata in rows:
                        md = {}
                        try: md = json.loads(metadata or '{}')
                        except Exception: md = {}
                        if not (md.get('legacy_fact') or md.get('legacy_note_id') is not None or scope == 'global'):
                            continue
                        new_status = "archived" if status in {"archived","deleted"} else LEGACY_UNRESOLVED_STATUS
                        conn.execute(
                            "UPDATE memory_items SET scope='user',owner_id=NULL,status=?,updated_at=?,metadata=? WHERE id=?",
                            (new_status, _now(), json.dumps({**md, "phase14_quarantine": True, "owner_resolution": "unknown",
                                                              "previous_scope": scope}, ensure_ascii=False, sort_keys=True), mid),
                        )
                        unresolved[f"quarantined_{kind}"] += 1
                        record("memory_items", mid, "global_personal_memory_owner_unknown", target_id=mid, target_kind=kind, target_scope="user",
                               target_status=new_status, decision="quarantined", reason="legacy personal memory was globally scoped without an explicit owner",
                               metadata={"previous_scope": scope, "key": key, "legacy_metadata": md})

                if dry_run:
                    completed = _now()
                    conn.execute(
                        "UPDATE legacy_memory_migration_runs SET completed_at=?,status='dry_run',migrated_counts=?,unresolved_counts=?,skipped_counts=? WHERE id=?",
                        (completed, json.dumps({}, sort_keys=True), json.dumps(dict(unresolved), sort_keys=True), json.dumps(dict(skipped), sort_keys=True), run_id),
                    )
                else:
                    completed = _now()
                    conn.execute(
                        "UPDATE legacy_memory_migration_runs SET completed_at=?,status='completed',migrated_counts=?,unresolved_counts=?,skipped_counts=? WHERE id=?",
                        (completed, json.dumps(dict(migrated), sort_keys=True), json.dumps(dict(unresolved), sort_keys=True), json.dumps(dict(skipped), sort_keys=True), run_id),
                    )
                    conn.execute(
                        "INSERT INTO memory_migration_meta(schema_name,schema_version,last_run_id,applied_at,status) VALUES(?,?,?,?,?) "
                        "ON CONFLICT(schema_name) DO UPDATE SET last_run_id=excluded.last_run_id,applied_at=excluded.applied_at,status=excluded.status",
                        (LEGACY_MIGRATION_SCHEMA_NAME, LEGACY_MIGRATION_SCHEMA_VERSION, run_id, completed, "completed"),
                    )
                return {"run_id": run_id, "status": "dry_run" if dry_run else "completed", "backup_path": backup,
                        "source_counts": source_counts, "migrated_counts": dict(migrated),
                        "unresolved_counts": dict(unresolved), "skipped_counts": dict(skipped)}
        finally:
            conn.close()

    def legacy_migration_status(self, *, conn=None, latest_only: bool = False) -> dict:
        own = conn is None
        if own:
            conn = self._connect()
        try:
            self._ensure_legacy_migration_schema(conn)
            row = conn.execute("SELECT id,started_at,completed_at,status,backup_path,source_counts,migrated_counts,unresolved_counts,skipped_counts,notes FROM legacy_memory_migration_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return {"status": "not_run", "source_counts": self._legacy_source_counts(conn)}
            result = {"run_id": row[0], "started_at": row[1], "completed_at": row[2], "status": row[3], "backup_path": row[4] or None,
                      "source_counts": json.loads(row[5] or '{}'), "migrated_counts": json.loads(row[6] or '{}'),
                      "unresolved_counts": json.loads(row[7] or '{}'), "skipped_counts": json.loads(row[8] or '{}'), "notes": row[9]}
            if latest_only:
                return result
            result["records"] = [
                {"id": r[0], "source_table": r[1], "source_id": r[2], "classification": r[3], "target_id": r[4],
                 "target_kind": r[5], "target_scope": r[6], "target_owner_id": r[7], "target_status": r[8],
                 "decision": r[9], "reason": r[10], "metadata": json.loads(r[11] or '{}'), "created_at": r[12]}
                for r in conn.execute("SELECT id,source_table,source_id,classification,target_id,target_kind,target_scope,target_owner_id,target_status,decision,reason,metadata,created_at FROM legacy_memory_migration_records WHERE run_id=? ORDER BY id", (row[0],)).fetchall()
            ]
            return result
        finally:
            if own:
                conn.close()

    def _resolve_memory_context(self, *, scope: str | None = None, owner_id: str | None = None,
                                session_id: str | None = None, run_id: str | None = None) -> dict[str, str | None]:
        from app.runtime.memory_context import current_memory_owner, current_memory_session, current_memory_run
        current_owner = current_memory_owner()
        current_session = current_memory_session()
        current_run = current_memory_run()
        effective_scope = LEGACY_SCOPE_ALIASES.get(str(scope).strip().lower(), str(scope).strip().lower()) if scope else USER
        if effective_scope not in MEMORY_SCOPES:
            raise ValueError(f"unsupported memory scope: {effective_scope}")
        if owner_id is not None and current_owner is not None and effective_scope != COMPANY and str(owner_id) != str(current_owner):
            raise PermissionError("owner_id conflicts with the active memory owner")
        if session_id is not None and current_session is not None and str(session_id) != str(current_session):
            raise PermissionError("session_id conflicts with the active memory session")
        if run_id is not None and current_run is not None and str(run_id) != str(current_run):
            raise PermissionError("run_id conflicts with the active memory run")
        effective_owner = str(owner_id or current_owner or self.default_owner_id)
        effective_session = session_id or current_session
        effective_run = run_id or current_run
        if effective_scope in {COMPANY, USER, SESSION, RUN} and not effective_owner:
            raise ValueError("owner_id is required for company/user/session/run memory")
        if effective_scope in {SESSION, RUN} and not effective_session:
            raise ValueError("session_id is required for session/run memory")
        if effective_scope == RUN and not effective_run:
            raise ValueError("run_id is required for run memory")
        if effective_scope in {GLOBAL_SYSTEM, KNOWLEDGE}:
            effective_owner = None
            if effective_scope == GLOBAL_SYSTEM:
                effective_session = None
                effective_run = None
        return {"scope": effective_scope, "owner_id": effective_owner, "session_id": effective_session, "run_id": effective_run}

    def _memory_scope_where(self, *, scope: str | None = None, owner_id: str | None = None,
                            session_id: str | None = None, run_id: str | None = None) -> tuple[str, tuple]:
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        parts=["scope=?"]; params:[str]=[str(ctx["scope"])]
        if ctx["scope"] in {COMPANY, USER, SESSION, RUN}:
            parts.append("owner_id=?"); params.append(str(ctx["owner_id"]))
        if ctx["scope"] in {SESSION, RUN}:
            parts.append("session_id=?"); params.append(str(ctx["session_id"]))
        if ctx["scope"] == RUN:
            parts.append("run_id=?"); params.append(str(ctx["run_id"]))
        return " AND ".join(parts), tuple(params)

    def _q(self, sql: str, params=()):
        conn = self._connect()
        try:
            with conn:
                return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def add_note(self, text: str, importance: int = 3, tags=(), source: str = "user", confidence: float = 1.0, *,
                 owner_id: str | None = None, session_id: str | None = None) -> int:
        text = str(text).strip()
        if not text:
            raise ValueError("الملاحظة فاضية")
        from app.knowledge.memory_extraction import contains_secret_pattern
        if contains_secret_pattern(text):
            raise ValueError("لا يمكن حفظ أسرار أو بيانات اعتماد في ذاكرة الوكيل")
        return self.remember(text, kind="note", scope=USER, owner_id=owner_id, session_id=session_id,
                             source=source, confidence=confidence, importance=importance,
                             metadata={"tags": list(tags)}, reason="add_note")

    def list_notes(self, *, owner_id: str | None = None) -> list[str]:
        return [row["value"] for row in self.list_memories(kind="note", scope=USER, owner_id=owner_id, limit=100000)]

    def search_notes(self, query: str, top_k: int = 10, *, owner_id: str | None = None) -> list[str]:
        hits = self.retrieve(query, top_k=top_k, kinds={"note"}, scope=USER, owner_id=owner_id)
        return [h["value"] for h in hits]

    def set_fact(self, key: str, value: str, source: str = "user", confidence: float = 1.0, *,
                 owner_id: str | None = None, session_id: str | None = None):
        key = self.canonical_key(key)
        value = str(value).strip()
        if not key or not value:
            raise ValueError("fact key/value cannot be empty")
        return self.remember(value, kind="fact", key=key, scope=USER, owner_id=owner_id, session_id=session_id,
                             source=source, confidence=confidence, importance=5,
                             metadata={"canonical_fact": 1}, reason="set_fact")

    def get_fact(self, key: str, *, owner_id: str | None = None, session_id: str | None = None) -> str | None:
        key = self.canonical_key(key)
        ctx = self._resolve_memory_context(scope=USER, owner_id=owner_id, session_id=session_id)
        now = _now()
        rows = self._q("SELECT value FROM memory_items WHERE kind='fact' AND key=? AND scope=? AND owner_id=? AND status='active' AND (valid_at IS NULL OR valid_at <= ?) AND (expires_at IS NULL OR expires_at >= ?) AND (invalid_at IS NULL OR invalid_at > ?) ORDER BY revision DESC,id DESC LIMIT 1",
                        (key, ctx["scope"], ctx["owner_id"], now, now, now))
        return rows[0][0] if rows else None

    def delete_fact(self, key: str, *, owner_id: str | None = None, session_id: str | None = None) -> bool:
        return self.forget(self.canonical_key(key), scope=USER, owner_id=owner_id, session_id=session_id, kind="fact", reason="forget_fact") > 0

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

    def recall_context(self, query: str, limit: int = 5, *, scope: str | None = None,
                       owner_id: str | None = None, session_id: str | None = None,
                       run_id: str | None = None, memory_plan=None, intent: str | None = None) -> dict:
        """Query-aware unified recall under one explicit ownership boundary.

        Phase 12 selects the smallest justified memory classes before touching a store.
        ``memory_plan`` can be supplied by the canonical semantic frame; direct callers
        receive a conservative generic-memory plan for compatibility.
        """
        from app.knowledge.memory_query import MemoryQueryPlan, plan_memory_query

        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        if isinstance(memory_plan, dict):
            memory_plan = MemoryQueryPlan(
                str(memory_plan.get('need') or 'none'),
                tuple(str(x) for x in (memory_plan.get('memory_types') or ())),
                tuple(str(x) for x in (memory_plan.get('stores') or ())),
                str(memory_plan.get('rationale') or ''),
                float(memory_plan.get('confidence') or 0.0),
            )
        if memory_plan is None:
            memory_plan = plan_memory_query(query, intent=intent or 'memory_search')

        requested = set(memory_plan.memory_types)
        semantic: list[dict] = []
        notes: list[dict] = []
        episodic: list[dict] = []
        procedural: list[dict] = []
        temporal: dict[str, list] = {}
        working: list[dict] = []
        graph: list[dict] = []
        knowledge: list[dict] = []
       
        # Durable personal facts/preferences/notes only when the semantic need allows them.
        durable_types = requested & {'fact', 'preference', 'note'}
        if durable_types:
            hits = self.retrieve(
                query, top_k=limit, kinds=durable_types, scope=ctx['scope'], owner_id=ctx['owner_id'],
                session_id=ctx['session_id'], run_id=ctx['run_id'],
            )
            semantic = [h for h in hits if h.get('kind') in {'fact', 'preference'}]
            notes = [h for h in hits if h.get('kind') == 'note']
            temporal = project(self, query, limit, scope=ctx['scope'], owner_id=ctx['owner_id'],
                               session_id=ctx['session_id'], run_id=ctx['run_id'])

        if 'episode' in requested and ctx['scope'] in {USER, SESSION, RUN}:
            episodic = self.retrieve_episodes(
                query, owner_id=ctx['owner_id'], session_id=ctx['session_id'],
                run_id=ctx['run_id'], top_k=max(limit, 8)
            )[:limit]
            temporal = project(self, query, limit, scope=ctx['scope'], owner_id=ctx['owner_id'],
                               session_id=ctx['session_id'], run_id=ctx['run_id'])

        if 'procedural' in requested and ctx['scope'] in {USER, SESSION, RUN}:
            procedural = self.procedural_memory(
                query, top_k=limit, scope=ctx['scope'], owner_id=ctx['owner_id'],
                session_id=ctx['session_id'], run_id=ctx['run_id']
            )

        if 'working' in requested and ctx['session_id']:
            working = self.working_recall(ctx['session_id'], limit, owner_id=ctx['owner_id'])

        if requested & {'entity', 'relation'}:
            subject = str(query or '').strip()
            if subject:
                graph = self.graph(
                    subject, scope=ctx['scope'], owner_id=ctx['owner_id'], session_id=ctx['session_id'],
                    run_id=ctx['run_id'], limit=limit
                )

        if 'knowledge' in requested:
            # Knowledge is a separate logical lane. Query it under KNOWLEDGE scope rather
            # than the caller's USER scope, and never attach personal owner/session context.
            knowledge_hits = self.retrieve(
                query, top_k=limit, kinds={'knowledge'}, scope=KNOWLEDGE, owner_id=None,
                session_id=None, run_id=None
            )
            knowledge = knowledge_hits[:limit]
            # Temporal eligibility is already applied by retrieve(); do not project personal
            # notes/runs into a knowledge query. Historical knowledge can be requested through
            # the normal as-of retrieval API without mixing stores.

        # Working/procedural/entity lanes intentionally remain empty when not selected.
        return {
            'semantic': semantic[:limit],
            'notes': notes[:limit],
            'episodic': episodic[:limit],
            'procedural': procedural[:limit],
            'temporal': temporal,
            'working': working[:limit],
            'graph': graph[:limit],
            'knowledge': knowledge[:limit],
            'memory_plan': memory_plan.to_dict(),
        }

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
        (mid, kind, key, value, scope, owner_id, session_id, run_id, source, source_ref, confidence,
         importance, sensitivity, status, created_at, updated_at, valid_at, invalid_at,
         expires_at, last_accessed, access_count, revision, supersedes_id, metadata) = row
        try:
            md = json.loads(metadata) if metadata else {}
        except Exception:
            md = {}
        return MemoryItem(
            id=int(mid), kind=kind, key=key, value=value, scope=scope, owner_id=owner_id,
            session_id=session_id, run_id=run_id, source=source, source_ref=source_ref,
            confidence=float(confidence), importance=int(importance), sensitivity=sensitivity,
            status=status, created_at=created_at, updated_at=updated_at, valid_at=valid_at,
            invalid_at=invalid_at, expires_at=expires_at, last_accessed=last_accessed,
            access_count=int(access_count), revision=int(revision), supersedes_id=supersedes_id,
            metadata=md,
        )

    def _active_memory_rows(self, *, scope: str | None = None, kinds: set[str] | None = None,
                            owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None):
        where=["status='active'"]; params=[]
        scope_sql, scope_params=self._memory_scope_where(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        where.append(scope_sql); params.extend(scope_params)
        if kinds:
            marks=','.join('?' for _ in kinds); where.append(f"kind IN ({marks})"); params.extend(sorted(kinds))
        return self._q("SELECT id,kind,key,value,scope,owner_id,session_id,run_id,source,source_ref,confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,last_accessed,access_count,revision,supersedes_id,metadata FROM memory_items WHERE " + " AND ".join(where) + " ORDER BY updated_at DESC,id DESC", params)

    def remember(self, value: str, *, kind: str = "fact", memory_type: str | None = None, key: str | None = None,
                 scope: str | None = None, owner_id: str | None = None, session_id: str | None = None,
                 run_id: str | None = None, source: str = "user", source_ref: str | None = None,
                 confidence: float = 1.0, importance: int = 3, sensitivity: str = "normal",
                 valid_at: str | None = None, invalid_at: str | None = None,
                 expires_at: str | None = None, metadata: dict | None = None,
                 reason: str = "remember") -> int:
        value = str(value).strip()
        if not value:
            raise ValueError("memory value is empty")
        if memory_type is not None:
            if kind != "fact" and str(kind) != str(memory_type):
                raise ValueError("kind and memory_type disagree")
            kind = str(memory_type).strip()
        if not str(kind).strip():
            raise ValueError("memory_type cannot be empty")
        kind = normalize_memory_type(kind)
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        scope, owner_id, session_id, run_id = ctx["scope"], ctx["owner_id"], ctx["session_id"], ctx["run_id"]
        validate_memory_type_operation(
            kind, scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id,
            operation="remember", source=source, key=key,
        )
        from app.knowledge.memory_extraction import contains_secret_pattern
        if sensitivity == "secret" or contains_secret_pattern(value):
            raise ValueError("secret material cannot be persisted in agent memory")
        confidence = max(0.0, min(1.0, float(confidence)))
        importance = max(1, min(5, int(importance)))
        normalized = " ".join(_tokens((key or "") + " " + value))
        now = _now()
        if valid_at is not None and invalid_at is not None and valid_at >= invalid_at:
            raise ValueError("valid_at must be before invalid_at")
        if valid_at is not None and expires_at is not None and valid_at >= expires_at:
            raise ValueError("valid_at must be before expires_at")
        if invalid_at is not None and expires_at is not None and expires_at < invalid_at:
            raise ValueError("expires_at cannot be before invalid_at")
        conn = self._connect()
        try:
            with conn:
                old = None
                current_now = now
                if key:
                    row = conn.execute(
                        "SELECT id,value,revision,confidence,importance,status,valid_at,invalid_at,expires_at FROM memory_items WHERE kind=? AND key=? AND scope=? AND owner_id IS ? AND status='active' AND (valid_at IS NULL OR valid_at <= ?) AND (invalid_at IS NULL OR invalid_at > ?) AND (expires_at IS NULL OR expires_at >= ?) ORDER BY revision DESC LIMIT 1",
                        (kind, key, scope, owner_id, current_now, current_now, current_now)).fetchone()
                    old = row
                else:
                    row = conn.execute(
                        "SELECT id,value,revision,confidence,importance,status,valid_at,invalid_at,expires_at FROM memory_items WHERE kind=? AND key IS NULL AND scope=? AND owner_id IS ? AND status='active' AND normalized=? AND (valid_at IS NULL OR valid_at <= ?) AND (invalid_at IS NULL OR invalid_at > ?) AND (expires_at IS NULL OR expires_at >= ?) ORDER BY revision DESC LIMIT 1",
                        (kind, scope, owner_id, normalized, current_now, current_now, current_now)).fetchone()
                    old = row
                if old and old[1].strip() == value:
                    current = conn.execute("SELECT source,source_ref,owner_id,session_id,run_id,expires_at,metadata FROM memory_items WHERE id=?", (old[0],)).fetchone()
                    current = current or ("system", None, owner_id, None, None, None, "{}")
                    source_rank = {"auto": 1, "system": 2, "user": 3}
                    kept_source = source if source_rank.get(source, 1) >= source_rank.get(current[0], 1) else current[0]
                    kept_source_ref = source_ref or current[1]
                    kept_owner = owner_id if owner_id is not None else current[2]
                    kept_session = session_id or current[3]
                    kept_run = run_id or current[4]
                    kept_expiry = expires_at or current[5]
                    kept_metadata = metadata if metadata else (json.loads(current[6]) if current[6] else {})
                    conn.execute(
                        "UPDATE memory_items SET confidence=?,importance=?,updated_at=?,source=?,source_ref=?,owner_id=?,session_id=?,run_id=?,expires_at=?,metadata=? WHERE id=?",
                        (max(float(old[3]), confidence), max(int(old[4]), importance), now, kept_source, kept_source_ref, kept_owner, kept_session, kept_run,
                         kept_expiry, json.dumps(kept_metadata, ensure_ascii=False, default=str), old[0]))
                    conn.execute("INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts,owner_id,scope,session_id,run_id,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (old[0], old[2], "CONFIRM", old[1], value, reason, source, now, owner_id, scope, session_id, run_id, "active"))
                    return int(old[0])
                if old:
                    revision = int(old[2]) + 1
                else:
                    if key:
                        max_row = conn.execute(
                            "SELECT MAX(revision) FROM memory_items WHERE kind=? AND key=? AND scope=? AND owner_id IS ?",
                            (kind, key, scope, owner_id)).fetchone()
                    else:
                        max_row = conn.execute(
                            "SELECT MAX(revision) FROM memory_items WHERE kind=? AND key IS NULL AND scope=? AND owner_id IS ? AND normalized=?",
                            (kind, scope, owner_id, normalized)).fetchone()
                    revision = int(max_row[0] or 0) + 1
                supersedes = int(old[0]) if old else None
                if old:
                    old_effective_end = valid_at or now
                    old_valid_at = old[6]
                    if old_valid_at and old_effective_end <= old_valid_at:
                        raise ValueError("valid_at must be after the superseded memory's valid_at")
                    conn.execute("UPDATE memory_items SET status='superseded',invalid_at=?,updated_at=? WHERE id=?", (old_effective_end, now, old[0]))
                    conn.execute("INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts,owner_id,scope,session_id,run_id,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (old[0], old[2], "SUPERSEDE", old[1], value, reason, source, now, owner_id, scope, session_id, run_id, "superseded"))
                cur = conn.execute(
                    "INSERT INTO memory_items(kind,key,value,normalized,scope,owner_id,session_id,run_id,source,source_ref,confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,revision,supersedes_id,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (kind, key, value, normalized, scope, owner_id, session_id, run_id, source, source_ref, confidence, importance,
                     sensitivity, "active", now, now, valid_at, invalid_at, expires_at, revision, supersedes,
                     json.dumps(metadata or {}, ensure_ascii=False, default=str)),
                )
                mid = int(cur.lastrowid)
                validate_memory_record_mapping({
                    "id": mid, "memory_type": kind, "owner_id": owner_id, "scope": scope,
                    "session_id": session_id, "run_id": run_id, "key": key, "value": value,
                    "normalized_value": normalized, "source": source, "source_ref": source_ref,
                    "confidence": confidence, "importance": importance, "created_at": now,
                    "updated_at": now, "valid_at": valid_at, "invalid_at": invalid_at,
                    "expires_at": expires_at, "revision": revision, "status": "active",
                    "supersedes_id": supersedes, "metadata": metadata or {},
                }, require_id=True)
                primary_action = "ADD" if old is None else ("CORRECT" if reason == "correction" else "UPDATE")
                if reason == "restore_history":
                    primary_action = "RESTORE"
                conn.execute("INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts,owner_id,scope,session_id,run_id,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (mid, revision, primary_action, old[1] if old else None, value, reason, source, now, owner_id, scope, session_id, run_id, "active"))
                return mid
        finally:
            conn.close()

    def update(self, value: str, **kwargs) -> int:
        """Canonical update operation; versioning remains owned by ``remember``."""
        kwargs.setdefault("reason", "update")
        return self.remember(value, **kwargs)

    def correct(self, value: str, **kwargs) -> int:
        """Canonical correction operation; corrections supersede the active keyed value."""
        kwargs.setdefault("reason", "correction")
        return self.remember(value, **kwargs)

    def add_memory_candidate(self, candidate: MemoryCandidate, **kwargs) -> int:
        return self.remember(candidate.value, kind=candidate.kind, key=candidate.key,
                             confidence=candidate.confidence, importance=candidate.importance,
                             source=candidate.source, sensitivity=candidate.sensitivity,
                             valid_at=candidate.valid_at, invalid_at=candidate.invalid_at,
                             expires_at=candidate.expires_at, metadata=candidate.metadata, **kwargs)

    def supersede(self, memory_id: int, value: str, *, reason: str = "supersede",
                  valid_at: str | None = None, invalid_at: str | None = None,
                  expires_at: str | None = None, scope: str | None = None, owner_id: str | None = None,
                  session_id: str | None = None, run_id: str | None = None, metadata: dict | None = None) -> int:
        row = self.get_memory(memory_id, include_inactive=True, scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        if not row:
            raise KeyError(f"memory {memory_id} not found in the active owner/scope")
        target_valid = valid_at or _now()
        old_valid = row.get("valid_at")
        if old_valid and target_valid <= old_valid:
            raise ValueError("valid_at must be after the superseded memory's valid_at")
        return self.remember(value, kind=row["kind"], key=row.get("key"), scope=row["scope"], owner_id=row.get("owner_id"),
                             session_id=row.get("session_id"), run_id=row.get("run_id"), source="user",
                             source_ref=row.get("source_ref"), confidence=row.get("confidence", 1.0),
                             importance=row.get("importance", 3), sensitivity=row.get("sensitivity", "normal"),
                             valid_at=target_valid, invalid_at=invalid_at, expires_at=expires_at,
                             metadata=metadata if metadata is not None else row.get("metadata") or {}, reason=reason)

    def expire_memory(self, memory_id: int, *, at: str | None = None, reason: str = "expire",
                      scope: str | None = None, owner_id: str | None = None, session_id: str | None = None,
                      run_id: str | None = None) -> bool:
        row = self.get_memory(memory_id, include_inactive=True, scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        if not row:
            return False
        effective = at or _now()
        current_valid = row.get("valid_at")
        if current_valid and effective <= current_valid:
            raise ValueError("expiration must be after valid_at")
        current_expiry = row.get("expires_at")
        if current_expiry and effective >= current_expiry:
            effective = current_expiry
        status = "expired" if effective <= _now() else row.get("status", "active")
        now = _now()
        self._q("UPDATE memory_items SET expires_at=?,status=?,updated_at=? WHERE id=? AND owner_id=?",
                 (effective, status, now, int(memory_id), row.get("owner_id")))
        self._q("INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts,owner_id,scope,session_id,run_id,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(memory_id), row["revision"], "EXPIRE", row["value"], row["value"], reason, "user", now, row.get("owner_id"), row.get("scope"), row.get("session_id"), row.get("run_id"), status))
        return True

    def memory_timeline(self, *, key: str | None = None, memory_id: int | None = None,
                        scope: str | None = None, owner_id: str | None = None, session_id: str | None = None,
                        run_id: str | None = None, limit: int = 100) -> list[dict]:
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        scope_sql, scope_params = self._memory_scope_where(scope=ctx["scope"], owner_id=ctx["owner_id"],
                                                           session_id=ctx["session_id"], run_id=ctx["run_id"])
        where = [scope_sql]
        params = list(scope_params)
        if memory_id is not None:
            where.append("(id=? OR supersedes_id=?)")
            params.extend([int(memory_id), int(memory_id)])
        elif key is not None:
            where.append("key=?")
            params.append(self.canonical_key(key))
        sql = "SELECT id,kind,key,value,scope,owner_id,session_id,run_id,source,source_ref,confidence,importance,status,created_at,updated_at,valid_at,invalid_at,expires_at,revision,supersedes_id,metadata FROM memory_items WHERE " + " AND ".join(where) + " ORDER BY revision ASC,id ASC LIMIT ?"
        params.append(max(1, int(limit)))
        rows = self._q(sql, tuple(params))
        out = []
        for r in rows:
            try:
                md = json.loads(r[-1]) if r[-1] else {}
            except Exception:
                md = {}
            out.append({"id": r[0], "kind": r[1], "key": r[2], "value": r[3], "scope": r[4], "owner_id": r[5],
                        "session_id": r[6], "run_id": r[7], "source": r[8], "source_ref": r[9],
                        "confidence": r[10], "importance": r[11], "status": r[12], "created_at": r[13],
                        "updated_at": r[14], "valid_at": r[15], "invalid_at": r[16], "expires_at": r[17],
                        "revision": r[18], "supersedes_id": r[19], "metadata": md})
        return out

    def retrieve_as_of(self, query: str, as_of: str, *, top_k: int = 8, kinds: set[str] | None = None,
                       scope: str | None = None, owner_id: str | None = None, session_id: str | None = None,
                       run_id: str | None = None) -> list[dict]:
        from app.knowledge.memory_schema import _parse_timestamp
        _parse_timestamp("as_of", as_of)
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        # Historical queries must include superseded records; build a full scoped timeline.
        scope_sql, scope_params = self._memory_scope_where(scope=ctx["scope"], owner_id=ctx["owner_id"],
                                                           session_id=ctx["session_id"], run_id=ctx["run_id"])
        where = [scope_sql, "(valid_at IS NULL OR valid_at <= ?)", "(invalid_at IS NULL OR invalid_at > ?)",
                 "(expires_at IS NULL OR expires_at > ?)"]
        params = [*scope_params, as_of, as_of, as_of]
        if kinds:
            marks = ",".join("?" for _ in kinds)
            where.append(f"kind IN ({marks})")
            params.extend(sorted(kinds))
        historical_rows = self._q("SELECT id,kind,key,value,scope,owner_id,session_id,run_id,source,source_ref,confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,last_accessed,access_count,revision,supersedes_id,metadata FROM memory_items WHERE " + " AND ".join(where) + " ORDER BY revision DESC,id DESC", tuple(params))
        items = [self._memory_row_to_item(r) for r in historical_rows]
        # For historical retrieval, treat the matching historical records as searchable evidence
        # without changing their stored status.
        hits = hybrid_search(
            items, query, top_k=top_k, kinds=kinds, scope=ctx["scope"], owner_id=ctx["owner_id"],
            session_id=ctx["session_id"], run_id=ctx["run_id"], as_of=as_of,
        )
        return [{"id": h.item.id, "kind": h.item.kind, "key": h.item.key, "value": h.item.value,
                 "scope": h.item.scope, "owner_id": h.item.owner_id, "source": h.item.source,
                 "confidence": h.item.confidence, "importance": h.item.importance, "status": h.item.status,
                 "revision": h.item.revision, "valid_at": h.item.valid_at, "invalid_at": h.item.invalid_at,
                 "expires_at": h.item.expires_at, "created_at": h.item.created_at, "updated_at": h.item.updated_at,
                 "score": round(h.score, 4), "reasons": list(h.reasons), "metadata": h.item.metadata}
                for h in hits]

    def restore_history(self, memory_id: int, *, scope: str | None = None, owner_id: str | None = None,
                        session_id: str | None = None, run_id: str | None = None, reason: str = "restore_history") -> int:
        row = self.get_memory(memory_id, include_inactive=True, scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        if not row:
            raise KeyError(f"memory {memory_id} not found in the active owner/scope")
        now = _now()
        return self.remember(row["value"], kind=row["kind"], key=row.get("key"), scope=row["scope"], owner_id=row.get("owner_id"),
                             session_id=row.get("session_id"), run_id=row.get("run_id"), source="restore",
                             source_ref=f"memory:{memory_id}", confidence=row.get("confidence", 1.0),
                             importance=row.get("importance", 3), sensitivity=row.get("sensitivity", "normal"),
                             valid_at=now, metadata={**(row.get("metadata") or {}), "restored_from": int(memory_id)}, reason=reason)

    def retrieve(self, query: str, *, top_k: int = 8, kinds: set[str] | None = None,
                      scope: str | None = None, owner_id: str | None = None, session_id: str | None = None,
                      run_id: str | None = None, include_expired: bool = False) -> list[dict]:
        ctx=self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        scope, owner_id, session_id, run_id = ctx["scope"], ctx["owner_id"], ctx["session_id"], ctx["run_id"]
        rows = self._active_memory_rows(scope=scope, kinds=kinds, owner_id=owner_id, session_id=session_id, run_id=run_id)
        items = [self._memory_row_to_item(r) for r in rows]
        if kinds is None or "episode" in kinds:
            episode_rows = self._q("SELECT id,owner_id,session_id,run_id,user_text,assistant_text,outcome,summary,ts,tool_events,entities,experience_kind,metadata FROM memory_episodes ORDER BY id DESC LIMIT 500")
            for eid, eowner, sid, rid, user_text, assistant_text, outcome, summary, ts, tool_events, entities, experience_kind, metadata in episode_rows:
                if outcome not in (None, "completed"):
                    continue
                if scope in {USER, SESSION, RUN} and eowner != owner_id:
                    continue
                if scope == SESSION and sid != session_id:
                    continue
                if scope == RUN and (sid != session_id or rid != run_id):
                    continue
                if scope in {GLOBAL_SYSTEM, KNOWLEDGE}:
                    continue
                try: md = json.loads(metadata) if metadata else {}
                except Exception: md = {}
                try: tool_data = json.loads(tool_events) if tool_events else []
                except Exception: tool_data = []
                try: entity_data = json.loads(entities) if entities else []
                except Exception: entity_data = []
                md = dict(md)
                md.setdefault("entities", entity_data)
                md.setdefault("tool_events", tool_data)
                md.setdefault("experience_kind", experience_kind or "interaction")
                item = MemoryItem(id=-int(eid), kind="episode", key=None,
                                  value=(summary or user_text or "").strip(), scope=scope, owner_id=eowner, session_id=sid, run_id=rid,
                                  source="episode", source_ref=f"episode:{eid}", confidence=1.0, importance=3,
                                  sensitivity="normal", status="active", created_at=ts, updated_at=ts,
                                  metadata={**md, "assistant_text": assistant_text, "outcome": outcome})
                items.append(item)
        hits = hybrid_search(
            items, query, top_k=top_k, kinds=kinds, scope=scope, owner_id=owner_id,
            session_id=session_id, run_id=run_id, include_expired=include_expired,
        )
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
             "scope": h.item.scope, "owner_id": h.item.owner_id, "source": h.item.source, "confidence": h.item.confidence,
             "importance": h.item.importance, "status": h.item.status, "revision": h.item.revision,
             "valid_at": h.item.valid_at, "invalid_at": h.item.invalid_at, "expires_at": h.item.expires_at,
             "created_at": h.item.created_at, "updated_at": h.item.updated_at, "score": round(h.score, 4),
             "reasons": list(h.reasons), "metadata": h.item.metadata}
            for h in hits
        ]

    def list_memories(self, *, kind: str | None = None, scope: str | None = None, limit: int = 100,
                      include_archived: bool = False, owner_id: str | None = None, session_id: str | None = None,
                      run_id: str | None = None) -> list[dict]:
        scope_sql, scope_params = self._memory_scope_where(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        where=[scope_sql]; params=list(scope_params)
        if not include_archived:
            now=_now()
            where += ["status='active'", "(valid_at IS NULL OR valid_at <= ?)", "(invalid_at IS NULL OR invalid_at > ?)", "(expires_at IS NULL OR expires_at >= ?)"]
            params += [now,now,now]
        if kind:
            where.append("kind=?"); params.append(kind)
        sql="SELECT id,kind,key,value,scope,owner_id,source,confidence,importance,status,revision,valid_at,invalid_at,expires_at,updated_at,metadata FROM memory_items WHERE " + " AND ".join(where) + " ORDER BY importance DESC,updated_at DESC,id DESC LIMIT ?"
        params.append(max(1,int(limit)))
        rows=self._q(sql,tuple(params)); out=[]
        for r in rows:
            try: md=json.loads(r[-1]) if r[-1] else {}
            except Exception: md={}
            out.append({"id":r[0],"kind":r[1],"key":r[2],"value":r[3],"scope":r[4],"owner_id":r[5],"source":r[6],"confidence":r[7],"importance":r[8],"status":r[9],"revision":r[10],"valid_at":r[11],"invalid_at":r[12],"expires_at":r[13],"updated_at":r[14],"metadata":md})
        return out

    def get_memory(self, memory_id: int, *, include_inactive: bool = False, scope: str | None = None, owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None) -> dict | None:
        ctx=self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        sql="SELECT id,kind,key,value,scope,owner_id,session_id,run_id,source,source_ref,confidence,importance,sensitivity,status,created_at,updated_at,valid_at,invalid_at,expires_at,last_accessed,access_count,revision,supersedes_id,metadata FROM memory_items WHERE id=? AND scope=?"
        params=[int(memory_id),ctx["scope"]]
        if ctx["scope"] in {USER,SESSION,RUN}: sql += " AND owner_id=?"; params.append(ctx["owner_id"])
        if ctx["scope"] == SESSION: sql += " AND session_id=?"; params.append(ctx["session_id"])
        if ctx["scope"] == RUN: sql += " AND session_id=? AND run_id=?"; params += [ctx["session_id"],ctx["run_id"]]
        if not include_inactive: sql += " AND status='active'"
        rows=self._q(sql,tuple(params))
        return asdict(self._memory_row_to_item(rows[0])) if rows else None

    def memory_history(self, *, memory_id: int | None = None, key: str | None = None, scope: str | None = None,
                       owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None, limit: int = 50) -> list[dict]:
        scope_sql, scope_params=self._memory_scope_where(scope=scope,owner_id=owner_id,session_id=session_id,run_id=run_id)
        where=[]; params=[]
        if memory_id is not None:
            where.append(f"memory_id IN (SELECT id FROM memory_items WHERE id=? AND {scope_sql})"); params += [int(memory_id), *scope_params]
        elif key:
            where.append(f"memory_id IN (SELECT id FROM memory_items WHERE key=? AND {scope_sql})"); params += [self.canonical_key(key), *scope_params]
        else:
            where.append(f"memory_id IN (SELECT id FROM memory_items WHERE {scope_sql})"); params += list(scope_params)
        params.append(max(1,int(limit)))
        rows=self._q("SELECT memory_id,revision,action,old_value,new_value,reason,source,ts,owner_id,scope,session_id,run_id,status FROM memory_history WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT ?",tuple(params))
        return [{"memory_id":r[0],"revision":r[1],"action":r[2],"old_value":r[3],"new_value":r[4],"reason":r[5],"source":r[6],"ts":r[7],
                 "owner_id":r[8],"scope":r[9],"session_id":r[10],"run_id":r[11],"status":r[12]} for r in rows]

    def forget_memory(self, memory_id: int, *, reason: str = "user_forget", scope: str | None = None, owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None) -> bool:
        row=self.get_memory(memory_id,scope=scope,owner_id=owner_id,session_id=session_id,run_id=run_id)
        if not row: return False
        now=_now()
        self._q("UPDATE memory_items SET status='deleted',invalid_at=?,updated_at=? WHERE id=?",(now,now,int(memory_id)))
        self._q("INSERT INTO memory_history(memory_id,revision,action,old_value,new_value,reason,source,ts,owner_id,scope,session_id,run_id,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(int(memory_id),row["revision"],"DELETE",row["value"],None,reason,"user",now,row.get("owner_id"),row.get("scope"),row.get("session_id"),row.get("run_id"),"deleted"))
        return True

    def forget_all(self, *, scope: str | None = None, owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None, include_episodes: bool = True) -> dict:
        ctx=self._resolve_memory_context(scope=scope,owner_id=owner_id,session_id=session_id,run_id=run_id)
        scope_sql, scope_params=self._memory_scope_where(scope=ctx["scope"],owner_id=ctx["owner_id"],session_id=ctx["session_id"],run_id=ctx["run_id"])
        rows=self._q("SELECT id FROM memory_items WHERE status='active' AND " + scope_sql,scope_params)
        deleted=sum(1 for (mid,) in rows if self.forget_memory(mid,scope=ctx["scope"],owner_id=ctx["owner_id"],session_id=ctx["session_id"],run_id=ctx["run_id"]))
        episodes_deleted=0
        if include_episodes and ctx["scope"] in {USER,SESSION,RUN}:
            q="SELECT COUNT(*) FROM memory_episodes WHERE owner_id=?"; qp=[ctx["owner_id"]]
            if ctx["scope"] in {SESSION,RUN}: q += " AND session_id=?"; qp.append(ctx["session_id"])
            if ctx["scope"]==RUN: q += " AND run_id=?"; qp.append(ctx["run_id"])
            episodes_deleted=int(self._q(q,tuple(qp))[0][0])
            delete_q = "DELETE FROM memory_episodes WHERE owner_id=?"
            delete_p=[ctx["owner_id"]]
            if ctx["scope"] in {SESSION,RUN}: delete_q += " AND session_id=?"; delete_p.append(ctx["session_id"])
            if ctx["scope"]==RUN: delete_q += " AND run_id=?"; delete_p.append(ctx["run_id"])
            self._q(delete_q,tuple(delete_p))
        if ctx["scope"] in {SESSION,RUN} and ctx["session_id"]:
            self._q("DELETE FROM memory_working WHERE owner_id=? AND session_id=?",(ctx["owner_id"],ctx["session_id"]))
        return {"deleted_memory_items":deleted,"deleted_episodes":episodes_deleted,"scope":ctx["scope"],"owner_id":ctx["owner_id"]}

    def forget(self, key: str, *, scope: str | None = None, owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None, kind: str | None = None, reason: str = "user_forget") -> int:
        ctx=self._resolve_memory_context(scope=scope,owner_id=owner_id,session_id=session_id,run_id=run_id)
        scope_sql,scope_params=self._memory_scope_where(scope=ctx["scope"],owner_id=ctx["owner_id"],session_id=ctx["session_id"],run_id=ctx["run_id"])
        where="key=? AND status='active' AND " + scope_sql; qp=[self.canonical_key(key),*scope_params]
        if kind: where += " AND kind=?"; qp.append(kind)
        rows=self._q("SELECT id FROM memory_items WHERE "+where,tuple(qp)); count=0
        for (mid,) in rows: count += int(self.forget_memory(mid,reason=reason,scope=ctx["scope"],owner_id=ctx["owner_id"],session_id=ctx["session_id"],run_id=ctx["run_id"]))
        return count

    def profile(self, *, scope: str | None = None, owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None, limit: int = 50) -> list[dict]:
        rows=self.list_memories(scope=scope,owner_id=owner_id,session_id=session_id,run_id=run_id,limit=max(limit*2,50),include_archived=False)
        return [row for row in rows if row["kind"] in {"fact","preference","goal","profile"}][:max(1,int(limit))]

    def record_episode(self, user_text: str, assistant_text: str = "", *, outcome: str | None = None,
                    summary: str | None = None, session_id: str | None = None, run_id: str | None = None,
                    owner_id: str | None = None, metadata: dict | None = None,
                    tool_events: list[dict] | tuple[dict, ...] | None = None,
                    entities: list[dict] | tuple[dict, ...] | None = None,
                    experience_kind: str = "interaction") -> int:
        if not str(user_text).strip():
            raise ValueError("episode user_text is empty")
        from app.knowledge.memory_extraction import redact_secrets
        ctx = self._resolve_memory_context(scope=USER, owner_id=owner_id, session_id=session_id, run_id=run_id)
        validate_memory_type_operation(
            "episode", scope=SESSION if ctx["session_id"] else USER, owner_id=ctx["owner_id"],
            session_id=ctx["session_id"], run_id=ctx["run_id"], operation="record_episode", source="runtime",
        )
        safe_user = redact_secrets(user_text.strip())
        safe_assistant = redact_secrets(str(assistant_text or "").strip())
        safe_summary = redact_secrets(str(summary or "").strip()) or None
        safe_tools = sanitize_tool_events(tool_events)
        safe_entities = sanitize_entities(entities)
        safe_kind = redact_secrets(str(experience_kind or "interaction").strip())[:80] or "interaction"
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO memory_episodes(owner_id,session_id,run_id,user_text,assistant_text,outcome,summary,ts,tool_events,entities,experience_kind,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ctx["owner_id"], ctx["session_id"], ctx["run_id"], safe_user, safe_assistant, outcome, safe_summary, _now(),
                     json.dumps(safe_tools, ensure_ascii=False, default=str),
                     json.dumps(safe_entities, ensure_ascii=False, default=str),
                     safe_kind,
                     json.dumps(sanitize_metadata(metadata), ensure_ascii=False, default=str)),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()

    def recent_episodes(self, session_id: str | None = None, limit: int = 12, *, owner_id: str | None = None,
                        run_id: str | None = None) -> list[dict]:
        requested_scope = RUN if run_id is not None else (SESSION if session_id is not None else USER)
        ctx = self._resolve_memory_context(scope=requested_scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        owner = ctx["owner_id"]
        session = ctx["session_id"]
        run = ctx["run_id"]
        query = "SELECT id,owner_id,session_id,run_id,user_text,assistant_text,outcome,summary,ts,tool_events,entities,experience_kind,metadata FROM memory_episodes WHERE owner_id=?"
        params: list[object] = [owner]
        if session:
            query += " AND session_id=?"; params.append(session)
        if run:
            query += " AND run_id=?"; params.append(run)
        query += " ORDER BY id DESC LIMIT ?"; params.append(int(limit))
        rows = self._q(query, tuple(params))
        out = []
        for r in rows:
            try: tool_data = json.loads(r[9]) if r[9] else []
            except Exception: tool_data = []
            try: entity_data = json.loads(r[10]) if r[10] else []
            except Exception: entity_data = []
            try: md = json.loads(r[12]) if r[12] else {}
            except Exception: md = {}
            out.append({"id": r[0], "episode_id": r[0], "owner_id": r[1], "session_id": r[2], "run_id": r[3],
                        "user_text": r[4], "user_message": r[4], "assistant_text": r[5], "assistant_response": r[5],
                        "outcome": r[6], "summary": r[7], "ts": r[8], "timestamp": r[8],
                        "tool_events": tool_data, "entities": entity_data, "experience_kind": r[11] or "interaction", "metadata": md})
        return out

    def get_episode(self, episode_id: int, *, owner_id: str | None = None, session_id: str | None = None,
                    run_id: str | None = None) -> dict | None:
        """Fetch one experience episode under the caller's ownership boundary."""
        requested_scope = SESSION if session_id is not None else USER
        ctx = self._resolve_memory_context(scope=requested_scope, owner_id=owner_id, session_id=session_id)
        sql = ("SELECT id,owner_id,session_id,run_id,user_text,assistant_text,outcome,summary,ts,tool_events,entities,experience_kind,metadata                FROM memory_episodes WHERE id=? AND owner_id=?")
        params: list[Any] = [int(episode_id), ctx["owner_id"]]
        if ctx["session_id"]:
            sql += " AND session_id=?"; params.append(ctx["session_id"])
        if ctx["run_id"]:
            sql += " AND run_id=?"; params.append(ctx["run_id"])
        elif run_id is not None:
            sql += " AND run_id=?"; params.append(str(run_id))
        rows = self._q(sql, tuple(params))
        if not rows:
            return None
        r = rows[0]
        try: tools = json.loads(r[9]) if r[9] else []
        except Exception: tools = []
        try: entities = json.loads(r[10]) if r[10] else []
        except Exception: entities = []
        try: metadata = json.loads(r[12]) if r[12] else {}
        except Exception: metadata = {}
        return canonical_episode_payload({"id": r[0], "owner_id": r[1], "session_id": r[2], "run_id": r[3],
            "user_text": r[4], "assistant_text": r[5], "outcome": r[6], "summary": r[7], "ts": r[8],
            "tool_events": tools, "entities": entities, "experience_kind": r[11], "metadata": metadata})

    def retrieve_episodes(self, query: str = "", *, top_k: int = 8, owner_id: str | None = None,
                          session_id: str | None = None, run_id: str | None = None) -> list[dict]:
        """Retrieve prior interactions/tasks independently from factual memory."""
        requested_scope = SESSION if session_id is not None else USER
        ctx = self._resolve_memory_context(scope=requested_scope, owner_id=owner_id, session_id=session_id)
        sql = ("SELECT id,owner_id,session_id,run_id,user_text,assistant_text,outcome,summary,ts,tool_events,entities,experience_kind,metadata                FROM memory_episodes WHERE owner_id=?")
        params: list[Any] = [ctx["owner_id"]]
        if ctx["session_id"]:
            sql += " AND session_id=?"; params.append(ctx["session_id"])
        if ctx["run_id"]:
            sql += " AND run_id=?"; params.append(ctx["run_id"])
        elif run_id is not None:
            sql += " AND run_id=?"; params.append(str(run_id))
        sql += " ORDER BY ts DESC,id DESC LIMIT ?"; params.append(max(1, min(int(top_k) * 20, 500)))
        rows = self._q(sql, tuple(params))
        scored: list[dict] = []
        for index, r in enumerate(rows):
            try: tools = json.loads(r[9]) if r[9] else []
            except Exception: tools = []
            try: entities = json.loads(r[10]) if r[10] else []
            except Exception: entities = []
            try: metadata = json.loads(r[12]) if r[12] else {}
            except Exception: metadata = {}
            episode = {"id": r[0], "owner_id": r[1], "session_id": r[2], "run_id": r[3],
                "user_text": r[4], "assistant_text": r[5], "outcome": r[6], "summary": r[7], "ts": r[8],
                "tool_events": tools, "entities": entities, "experience_kind": r[11], "metadata": metadata}
            score, reasons = score_episode(query, episode, rank=index)
            payload = canonical_episode_payload(episode)
            payload.update({"score": score, "reasons": reasons})
            scored.append(payload)
        scored.sort(key=lambda row: (-float(row["score"]), -int(row.get("episode_id") or 0)))
        return scored[:max(1, int(top_k))]

    def retrieve_experience(self, query: str = "", *, top_k: int = 8, owner_id: str | None = None,
                            session_id: str | None = None, run_id: str | None = None) -> list[dict]:
        return self.retrieve_episodes(query, top_k=top_k, owner_id=owner_id, session_id=session_id, run_id=run_id)

    def experience_timeline(self, *, owner_id: str | None = None, session_id: str | None = None,
                            run_id: str | None = None, limit: int = 50) -> list[dict]:
        return self.retrieve_episodes("", top_k=limit, owner_id=owner_id, session_id=session_id, run_id=run_id)

    def session_summary(self, session_id: str | None = None, *, owner_id: str | None = None,
                        limit: int = 20) -> dict:
        episodes = self.recent_episodes(session_id=session_id, owner_id=owner_id, limit=max(1, int(limit)))
        from collections import Counter
        counter = Counter()
        for episode in reversed(episodes):
            counter.update(t for t in _tokens((episode.get("user_text") or "") + " " + (episode.get("summary") or ""))
                            if len(t) > 2)
        stop = {"the", "and", "that", "this", "with", "from", "about", "you", "what", "does", "have",
                "من", "في", "على", "عن", "هذا", "هذه", "انا", "أنا", "هو", "هي"}
        topics = [token for token, _ in counter.most_common(10) if token not in stop][:6]
        return {"session_id": session_id, "owner_id": str(owner_id or self.default_owner_id),
                "episode_count": len(episodes), "topics": topics, "latest": episodes[0] if episodes else None,
                "recent": episodes[:min(5, len(episodes))]}

    def restore_memory(self, payload: dict, *, scope_override: str | None = None,
                       owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None,
                       include_episodes: bool = False) -> dict:
        if not isinstance(payload, dict) or payload.get("schema") != "personal-agent.memory.v1":
            raise ValueError("unsupported memory export schema")
        schema_version = int(payload.get("memory_schema_version", CANONICAL_MEMORY_SCHEMA_VERSION))
        if schema_version > CANONICAL_MEMORY_SCHEMA_VERSION:
            raise ValueError("memory export schema is newer than this runtime")
        imported_items = 0
        skipped_items = 0
        for row in payload.get("items", []):
            if row.get("status") != "active":
                continue
            try:
                target_scope = scope_override or row.get("scope") or USER
                # Never trust owner_id embedded in an export when restoring personal memory.
                target_owner = owner_id if target_scope in {USER, SESSION, RUN} else None
                target_session = session_id if target_scope in {SESSION, RUN} else None
                target_run = run_id if target_scope == RUN else None
                self.remember(row.get("value", ""), kind=row.get("kind", "fact"), key=row.get("key"),
                              scope=target_scope, owner_id=target_owner, session_id=target_session, run_id=target_run,
                              source="import", confidence=float(row.get("confidence", 0.8)),
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
                    episode_session = session_id if session_id is not None else episode.get("session_id")
                    episode_run = run_id if run_id is not None else episode.get("run_id")
                    self.record_episode(episode.get("user_text", episode.get("user_message", "")), episode.get("assistant_text", episode.get("assistant_response", "")),
                                        outcome=episode.get("outcome"), summary=episode.get("summary"),
                                        owner_id=owner_id, session_id=episode_session, run_id=episode_run,
                                        tool_events=episode.get("tool_events") or [], entities=episode.get("entities") or [],
                                        experience_kind=episode.get("experience_kind") or "interaction",
                                        metadata=episode.get("metadata") or {})
                    imported_episodes += 1
                except (TypeError, ValueError):
                    skipped_items += 1
        return {"imported_items": imported_items, "imported_episodes": imported_episodes, "skipped": skipped_items}

    def record_working_context(self, session_id: str, content: str, *, kind: str = "context", priority: int = 3,
                    owner_id: str | None = None, expires_at: str | None = None, metadata: dict | None = None) -> int:
        if not str(content).strip():
            raise ValueError("working context is empty")
        ctx = self._resolve_memory_context(scope=SESSION, owner_id=owner_id, session_id=session_id)
        validate_memory_type_operation(
            "working", scope=SESSION, owner_id=ctx["owner_id"], session_id=ctx["session_id"], run_id=None,
            operation="record_working_context", source="runtime", key=kind,
        )
        now = _now()
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO memory_working(owner_id,session_id,kind,content,priority,created_at,updated_at,expires_at,metadata) VALUES(?,?,?,?,?,?,?,?,?)",
                    (ctx["owner_id"], ctx["session_id"], kind, content, max(1, min(5, int(priority))), now, now, expires_at,
                     json.dumps(metadata or {}, ensure_ascii=False, default=str)),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()

    def working_recall(self, session_id: str, limit: int = 12, *, owner_id: str | None = None) -> list[dict]:
        ctx = self._resolve_memory_context(scope=SESSION, owner_id=owner_id, session_id=session_id)
        now = _now()
        rows = self._q(
            "SELECT id,owner_id,session_id,kind,content,priority,created_at,updated_at,expires_at,metadata FROM memory_working "
            "WHERE owner_id=? AND session_id=? AND (expires_at IS NULL OR expires_at>=?) "
            "ORDER BY priority DESC,updated_at DESC LIMIT ?",
            (ctx["owner_id"], ctx["session_id"], now, int(limit)),
        )
        out = []
        for r in rows:
            try: md = json.loads(r[9]) if r[9] else {}
            except Exception: md = {}
            out.append({"id": r[0], "owner_id": r[1], "session_id": r[2], "kind": r[3], "content": r[4],
                        "priority": r[5], "created_at": r[6], "updated_at": r[7], "expires_at": r[8], "metadata": md})
        return out

    def working_clear(self, session_id: str, *, owner_id: str | None = None) -> int:
        ctx = self._resolve_memory_context(scope=SESSION, owner_id=owner_id, session_id=session_id)
        rows = self._q("SELECT COUNT(*) FROM memory_working WHERE owner_id=? AND session_id=?", (ctx["owner_id"], ctx["session_id"]))
        count = int(rows[0][0]) if rows else 0
        self._q("DELETE FROM memory_working WHERE owner_id=? AND session_id=?", (ctx["owner_id"], ctx["session_id"]))
        return count

    @staticmethod
    def _canonical_entity_text(value: str) -> str:
        """Return one deterministic canonical representation for entity identity."""
        text = str(value or "").strip()
        if not text:
            raise ValueError("entity name cannot be empty")
        tokens = _tokens(text)
        canonical = " ".join(tokens).strip()
        if canonical:
            return canonical
        fallback = normalize(text).strip().casefold()
        if not fallback:
            raise ValueError("entity name cannot be empty")
        return fallback

    @staticmethod
    def _display_aliases(values) -> list[str]:
        aliases: list[str] = []
        for value in values or ():
            text = str(value or "").strip()
            if text:
                aliases.append(text)
        return list(dict.fromkeys(aliases))

    @classmethod
    def _normalized_alias_set(cls, values) -> set[str]:
        out: set[str] = set()
        for value in values or ():
            try:
                out.add(cls._canonical_entity_text(str(value)))
            except ValueError:
                continue
        return out

    def _entity_context_where(self, ctx: dict[str, str | None]) -> tuple[str, tuple]:
        parts = ["scope=?"]
        params: list[object] = [ctx["scope"]]
        if ctx["scope"] in {USER, SESSION, RUN}:
            parts.append("owner_id=?")
            params.append(ctx["owner_id"])
        if ctx["scope"] in {SESSION, RUN}:
            parts.append("session_id=?")
            params.append(ctx["session_id"])
        if ctx["scope"] == RUN:
            parts.append("run_id=?")
            params.append(ctx["run_id"])
        return " AND ".join(parts), tuple(params)

    def _entity_row(self, entity_id: int, ctx: dict[str, str | None]) -> tuple | None:
        where, params = self._entity_context_where(ctx)
        rows = self._q(
            "SELECT id,canonical,label,scope,owner_id,session_id,run_id,aliases,created_at,updated_at "
            "FROM memory_entities WHERE id=? AND " + where,
            (int(entity_id), *params),
        )
        return rows[0] if rows else None

    @staticmethod
    def _entity_to_dict(row: tuple) -> dict:
        try:
            aliases = json.loads(row[7]) if row[7] else []
        except Exception:
            aliases = []
        return {
            "id": int(row[0]), "canonical": row[1], "label": row[2], "scope": row[3],
            "owner_id": row[4], "session_id": row[5], "run_id": row[6],
            "aliases": list(aliases or []), "created_at": row[8], "updated_at": row[9],
        }

    def resolve_entity(self, name: str, *, scope: str | None = None, owner_id: str | None = None,
                       session_id: str | None = None, run_id: str | None = None) -> dict | None:
        """Resolve an entity by canonical identity or alias within one exact scope."""
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        validate_memory_type_operation(
            ENTITY, scope=ctx["scope"], owner_id=ctx["owner_id"], session_id=ctx["session_id"],
            run_id=ctx["run_id"], operation="resolve_entity", source="runtime", key=name,
        )
        canonical = self._canonical_entity_text(name)
        where, params = self._entity_context_where(ctx)
        rows = self._q(
            "SELECT id,canonical,label,scope,owner_id,session_id,run_id,aliases,created_at,updated_at "
            "FROM memory_entities WHERE " + where + " ORDER BY id ASC",
            params,
        )
        exact = [row for row in rows if row[1] == canonical]
        if exact:
            return self._entity_to_dict(exact[0])
        matches: list[tuple] = []
        for row in rows:
            try:
                aliases = json.loads(row[7]) if row[7] else []
            except Exception:
                aliases = []
            if canonical in self._normalized_alias_set(aliases):
                matches.append(row)
        if len(matches) > 1:
            raise ValueError(f"ambiguous entity alias: {name!r}")
        return self._entity_to_dict(matches[0]) if matches else None

    def link_entity(self, name: str, *, label: str = "entity", scope: str | None = None,
                    owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None,
                    aliases=()) -> int:
        """Create or resolve canonical entity identity without crossing ownership/session boundaries."""
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        validate_memory_type_operation(
            ENTITY, scope=ctx["scope"], owner_id=ctx["owner_id"], session_id=ctx["session_id"],
            run_id=ctx["run_id"], operation="link_entity", source="runtime", key=name,
        )
        canonical = self._canonical_entity_text(name)
        requested_aliases = self._display_aliases(aliases)
        now = _now()
        where, params = self._entity_context_where(ctx)
        conn = self._connect()
        try:
            with conn:
                rows = conn.execute(
                    "SELECT id,canonical,label,scope,owner_id,session_id,run_id,aliases,created_at,updated_at "
                    "FROM memory_entities WHERE " + where + " ORDER BY id ASC",
                    params,
                ).fetchall()
                exact = next((row for row in rows if row[1] == canonical), None)
                if exact:
                    existing = json.loads(exact[7]) if exact[7] else []
                    peers = [r for r in rows if r[0] != exact[0]]
                    peer_aliases = {
                        alias_norm
                        for peer in peers
                        for alias_norm in self._normalized_alias_set(json.loads(peer[7]) if peer[7] else [])
                    }
                    for alias in requested_aliases:
                        alias_norm = self._canonical_entity_text(alias)
                        if alias_norm != canonical and alias_norm in peer_aliases:
                            raise ValueError(f"alias already belongs to another entity: {alias!r}")
                    merged = self._display_aliases(existing + requested_aliases)
                    merged_norm = self._normalized_alias_set(merged)
                    if canonical in merged_norm:
                        merged = [a for a in merged if self._canonical_entity_text(a) != canonical]
                    conn.execute(
                        "UPDATE memory_entities SET label=?,aliases=?,updated_at=? WHERE id=?",
                        (str(label or exact[2] or "entity"), json.dumps(merged, ensure_ascii=False), now, exact[0]),
                    )
                    return int(exact[0])

                alias_matches: list[tuple] = []
                for row in rows:
                    try:
                        stored_aliases = json.loads(row[7]) if row[7] else []
                    except Exception:
                        stored_aliases = []
                    if canonical in self._normalized_alias_set(stored_aliases):
                        alias_matches.append(row)
                if len(alias_matches) > 1:
                    raise ValueError(f"ambiguous entity alias: {name!r}")
                if alias_matches:
                    row = alias_matches[0]
                    existing = json.loads(row[7]) if row[7] else []
                    merged = self._display_aliases(existing + requested_aliases + ([name] if canonical != row[1] else []))
                    # Never allow an alias to shadow a different canonical identity.
                    canonical_conflict = next((r for r in rows if r[1] == canonical and r[0] != row[0]), None)
                    if canonical_conflict:
                        raise ValueError(f"entity name conflicts with canonical identity: {name!r}")
                    conn.execute(
                        "UPDATE memory_entities SET label=?,aliases=?,updated_at=? WHERE id=?",
                        (str(label or row[2] or "entity"), json.dumps(merged, ensure_ascii=False), now, row[0]),
                    )
                    return int(row[0])

                # Reject aliases that collide with another canonical identity in this exact context.
                canonical_names = {r[1]: int(r[0]) for r in rows}
                peer_aliases = {
                    alias_norm
                    for row in rows
                    for alias_norm in self._normalized_alias_set(json.loads(row[7]) if row[7] else [])
                }
                clean_aliases = []
                for alias in requested_aliases:
                    alias_norm = self._canonical_entity_text(alias)
                    if alias_norm == canonical:
                        continue
                    if alias_norm in canonical_names:
                        raise ValueError(f"alias conflicts with canonical identity: {alias!r}")
                    if alias_norm in peer_aliases:
                        raise ValueError(f"alias already belongs to another entity: {alias!r}")
                    if alias_norm not in self._normalized_alias_set(clean_aliases):
                        clean_aliases.append(alias)

                cur = conn.execute(
                    "INSERT INTO memory_entities(canonical,label,scope,owner_id,session_id,run_id,aliases,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (canonical, str(label or "entity"), ctx["scope"], ctx["owner_id"], ctx["session_id"], ctx["run_id"],
                     json.dumps(clean_aliases, ensure_ascii=False), now, now),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()

    def update_entity(self, entity_id: int, *, canonical: str | None = None, label: str | None = None,
                      add_aliases=(), remove_aliases=(), scope: str | None = None, owner_id: str | None = None,
                      session_id: str | None = None, run_id: str | None = None) -> int:
        """Correct entity identity/aliases in place while preserving the previous canonical as an alias."""
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        row = self._entity_row(entity_id, ctx)
        if not row:
            raise KeyError(f"entity {entity_id} not found in the active owner/scope")
        old_canonical = row[1]
        new_canonical = self._canonical_entity_text(canonical) if canonical is not None else old_canonical
        existing_aliases = json.loads(row[7]) if row[7] else []
        aliases = self._display_aliases(existing_aliases + list(add_aliases or ()))
        if new_canonical != old_canonical:
            aliases.append(old_canonical)
        remove_norm = self._normalized_alias_set(remove_aliases)
        aliases = [a for a in aliases if self._canonical_entity_text(a) not in remove_norm and self._canonical_entity_text(a) != new_canonical]
        where, params = self._entity_context_where(ctx)
        peers = self._q(
            "SELECT id,canonical,aliases FROM memory_entities WHERE " + where + " AND id<>?",
            (*params, int(entity_id)),
        )
        if any(r[1] == new_canonical for r in peers):
            raise ValueError(f"entity canonical identity already exists: {new_canonical!r}")
        for peer in peers:
            peer_aliases = json.loads(peer[2]) if peer[2] else []
            peer_alias_norms = self._normalized_alias_set(peer_aliases)
            if new_canonical in peer_alias_norms:
                raise ValueError(f"entity canonical identity conflicts with alias: {new_canonical!r}")
            if any(self._canonical_entity_text(alias) in peer_alias_norms for alias in aliases):
                raise ValueError("entity alias already belongs to another entity")
            if any(self._canonical_entity_text(alias) == peer[1] for alias in aliases):
                raise ValueError("entity alias conflicts with another canonical identity")
        now = _now()
        self._q(
            "UPDATE memory_entities SET canonical=?,label=?,aliases=?,updated_at=? WHERE id=? AND " + where,
            (new_canonical, str(label if label is not None else row[2] or "entity"), json.dumps(self._display_aliases(aliases), ensure_ascii=False), now, int(entity_id), *params),
        )
        return int(entity_id)

    def link_relation(self, subject: str, predicate: str, object_value: str, *, scope: str | None = None,
                      owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None,
                      confidence: float = 1.0, source_memory_id: int | None = None,
                      valid_at: str | None = None, invalid_at: str | None = None, metadata: dict | None = None) -> int:
        """Add one typed relation; conflicting values remain separately traceable until explicitly corrected."""
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        validate_memory_type_operation(
            RELATION, scope=ctx["scope"], owner_id=ctx["owner_id"], session_id=ctx["session_id"],
            run_id=ctx["run_id"], operation="link_relation", source="runtime", key=predicate,
        )
        predicate_norm = self._canonical_entity_text(predicate)
        object_text = str(object_value or "").strip()
        if not object_text:
            raise ValueError("relation object cannot be empty")
        from app.knowledge.memory_schema import _parse_timestamp
        if valid_at is not None:
            _parse_timestamp("valid_at", valid_at)
        if invalid_at is not None:
            _parse_timestamp("invalid_at", invalid_at)
        if valid_at and invalid_at and _parse_timestamp("valid_at", valid_at) >= _parse_timestamp("invalid_at", invalid_at):
            raise ValueError("relation valid_at must be before invalid_at")
        source_confidence = max(0.0, min(1.0, float(confidence)))
        subject_id = self.link_entity(
            subject, scope=ctx["scope"], owner_id=ctx["owner_id"], session_id=ctx["session_id"], run_id=ctx["run_id"],
        )
        now = _now()
        conn = self._connect()
        try:
            with conn:
                old = conn.execute(
                    "SELECT id,revision FROM memory_relations WHERE subject_id=? AND predicate=? AND object_value=? "
                    "AND scope=? AND owner_id IS ? AND session_id IS ? AND run_id IS ? AND status='active' "
                    "AND (valid_at IS NULL OR valid_at <= ?) AND (invalid_at IS NULL OR invalid_at > ?) LIMIT 1",
                    (subject_id, predicate_norm, object_text, ctx["scope"], ctx["owner_id"], ctx["session_id"], ctx["run_id"], now, now),
                ).fetchone()
                if old:
                    conn.execute(
                        "UPDATE memory_relations SET confidence=?,valid_at=?,invalid_at=?,source_memory_id=?,metadata=?,updated_at=? WHERE id=?",
                        (source_confidence, valid_at, invalid_at, source_memory_id,
                         json.dumps(metadata or {}, ensure_ascii=False, default=str), now, old[0]),
                    )
                    return int(old[0])
                cur = conn.execute(
                    "INSERT INTO memory_relations(subject_id,predicate,object_value,scope,owner_id,session_id,run_id,confidence,status,valid_at,invalid_at,source_memory_id,revision,supersedes_id,created_at,updated_at,metadata) "
                    "VALUES(?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?)",
                    (subject_id, predicate_norm, object_text, ctx["scope"], ctx["owner_id"], ctx["session_id"], ctx["run_id"],
                     source_confidence, valid_at, invalid_at, source_memory_id, 1, None, now, now,
                     json.dumps(metadata or {}, ensure_ascii=False, default=str)),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()

    def _relation_row(self, relation_id: int, ctx: dict[str, str | None], *, include_inactive: bool = True) -> tuple | None:
        parts = ["id=?", "scope=?"]
        params: list[object] = [int(relation_id), ctx["scope"]]
        if ctx["scope"] in {USER, SESSION, RUN}:
            parts.append("owner_id=?")
            params.append(ctx["owner_id"])
        if ctx["scope"] in {SESSION, RUN}:
            parts.append("session_id=?")
            params.append(ctx["session_id"])
        if ctx["scope"] == RUN:
            parts.append("run_id=?")
            params.append(ctx["run_id"])
        if not include_inactive:
            parts.append("status='active'")
        rows = self._q(
            "SELECT id,subject_id,predicate,object_value,scope,owner_id,session_id,run_id,confidence,status,valid_at,invalid_at,source_memory_id,revision,supersedes_id,created_at,updated_at,metadata "
            "FROM memory_relations WHERE " + " AND ".join(parts), tuple(params)
        )
        return rows[0] if rows else None

    @staticmethod
    def _relation_to_dict(row: tuple) -> dict:
        try:
            md = json.loads(row[17]) if row[17] else {}
        except Exception:
            md = {}
        return {
            "id": int(row[0]), "subject_id": int(row[1]), "predicate": row[2], "object": row[3],
            "scope": row[4], "owner_id": row[5], "session_id": row[6], "run_id": row[7],
            "confidence": float(row[8]), "status": row[9], "valid_at": row[10], "invalid_at": row[11],
            "source_memory_id": row[12], "revision": int(row[13]), "supersedes_id": row[14],
            "created_at": row[15], "updated_at": row[16], "metadata": md,
        }

    def update_relation(self, relation_id: int, *, object_value: str | None = None, confidence: float | None = None,
                        valid_at: str | None = None, invalid_at: str | None = None,
                        source_memory_id: int | None = None, metadata: dict | None = None,
                        scope: str | None = None, owner_id: str | None = None,
                        session_id: str | None = None, run_id: str | None = None,
                        reason: str = "update_relation") -> int:
        """Create a new relation revision and supersede the old revision without losing history."""
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        old = self._relation_row(relation_id, ctx)
        if not old:
            raise KeyError(f"relation {relation_id} not found in the active owner/scope")
        if old[9] == "forgotten":
            raise ValueError("cannot update a forgotten relation")
        from app.knowledge.memory_schema import _parse_timestamp
        now = _now()
        new_valid = valid_at or now
        new_object = str(old[3] if object_value is None else object_value).strip()
        if not new_object:
            raise ValueError("relation object cannot be empty")
        new_confidence = float(old[8] if confidence is None else confidence)
        new_confidence = max(0.0, min(1.0, new_confidence))
        if _parse_timestamp("valid_at", new_valid) <= _parse_timestamp("created_at", old[15]) and old[10]:
            if _parse_timestamp("valid_at", new_valid) <= _parse_timestamp("valid_at", old[10]):
                raise ValueError("relation valid_at must be after the superseded relation's valid_at")
        if invalid_at is not None:
            _parse_timestamp("invalid_at", invalid_at)
            if _parse_timestamp("valid_at", new_valid) >= _parse_timestamp("invalid_at", invalid_at):
                raise ValueError("relation valid_at must be before invalid_at")
        else:
            invalid_at = None
        old_effective_invalid = invalid_at or new_valid
        if old[10] and _parse_timestamp("valid_at", new_valid) <= _parse_timestamp("valid_at", old[10]):
            raise ValueError("relation valid_at must be after the superseded relation's valid_at")
        payload = metadata if metadata is not None else old[17]
        if isinstance(payload, str):
            try: payload = json.loads(payload)
            except Exception: payload = {}
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE memory_relations SET status='superseded',invalid_at=?,updated_at=? WHERE id=?",
                    (old_effective_invalid, now, int(relation_id)),
                )
                cur = conn.execute(
                    "INSERT INTO memory_relations(subject_id,predicate,object_value,scope,owner_id,session_id,run_id,confidence,status,valid_at,invalid_at,source_memory_id,revision,supersedes_id,created_at,updated_at,metadata) "
                    "VALUES(?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?)",
                    (old[1], old[2], new_object, old[4], old[5], old[6], old[7], new_confidence,
                     new_valid, invalid_at, source_memory_id if source_memory_id is not None else old[12],
                     int(old[13]) + 1, int(relation_id), old[15], now,
                     json.dumps({**(payload or {}), "reason": reason, "supersedes_relation": int(relation_id)}, ensure_ascii=False, default=str)),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()

    def correct_relation(self, relation_id: int, **kwargs) -> int:
        """Canonical correction alias for update_relation."""
        kwargs.setdefault("reason", "correct_relation")
        return self.update_relation(relation_id, **kwargs)

    def forget_relation(self, relation_id: int, *, scope: str | None = None, owner_id: str | None = None,
                        session_id: str | None = None, run_id: str | None = None, reason: str = "forget_relation") -> bool:
        """Forget a relation without deleting its historical revision."""
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        row = self._relation_row(relation_id, ctx)
        if not row:
            return False
        now = _now()
        try:
            existing_metadata = json.loads(row[17]) if row[17] else {}
        except Exception:
            existing_metadata = {}
        self._q("UPDATE memory_relations SET status='forgotten',invalid_at=COALESCE(invalid_at,?),updated_at=?,metadata=? WHERE id=?",
                (now, now, json.dumps({**existing_metadata, "reason": reason}, ensure_ascii=False, default=str), int(relation_id)))
        return True

    def relation_history(self, relation_id: int | None = None, *, subject: str | None = None,
                         predicate: str | None = None, scope: str | None = None, owner_id: str | None = None,
                         session_id: str | None = None, run_id: str | None = None, limit: int = 50) -> list[dict]:
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        parts = ["scope=?"]
        params: list[object] = [ctx["scope"]]
        if ctx["scope"] in {USER, SESSION, RUN}:
            parts.append("owner_id=?"); params.append(ctx["owner_id"])
        if ctx["scope"] in {SESSION, RUN}:
            parts.append("session_id=?"); params.append(ctx["session_id"])
        if ctx["scope"] == RUN:
            parts.append("run_id=?"); params.append(ctx["run_id"])
        if relation_id is not None:
            parts.append("(id=? OR supersedes_id=?)"); params += [int(relation_id), int(relation_id)]
        elif subject is not None:
            subject_entity = self.resolve_entity(subject, scope=ctx["scope"], owner_id=ctx["owner_id"], session_id=ctx["session_id"], run_id=ctx["run_id"])
            if not subject_entity:
                return []
            parts.append("subject_id=?"); params.append(int(subject_entity["id"]))
        if predicate:
            parts.append("predicate=?"); params.append(self._canonical_entity_text(predicate))
        rows = self._q(
            "SELECT id,subject_id,predicate,object_value,scope,owner_id,session_id,run_id,confidence,status,valid_at,invalid_at,source_memory_id,revision,supersedes_id,created_at,updated_at,metadata "
            "FROM memory_relations WHERE " + " AND ".join(parts) + " ORDER BY revision ASC,id ASC LIMIT ?",
            tuple(params) + (max(1, int(limit)),),
        )
        return [self._relation_to_dict(row) for row in rows]

    def graph(self, subject: str, *, scope: str | None = None, owner_id: str | None = None,
              session_id: str | None = None, run_id: str | None = None, limit: int = 20,
              as_of: str | None = None) -> list[dict]:
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        entity = self.resolve_entity(subject, scope=ctx["scope"], owner_id=ctx["owner_id"], session_id=ctx["session_id"], run_id=ctx["run_id"])
        if not entity:
            return []
        from app.knowledge.memory_schema import _parse_timestamp
        moment = as_of or _now()
        _parse_timestamp("as_of", moment)
        parts = [
            "r.subject_id=?", "r.scope=?", "r.owner_id IS ?", "r.session_id IS ?", "r.run_id IS ?",
            "(r.valid_at IS NULL OR r.valid_at <= ?)", "(r.invalid_at IS NULL OR r.invalid_at > ?)",
        ]
        params: list[object] = [int(entity["id"]), ctx["scope"], ctx["owner_id"], ctx["session_id"], ctx["run_id"], moment, moment]
        if as_of is None:
            parts.append("r.status='active'")
        else:
            parts.append("r.status<>'forgotten'")
        rows = self._q(
            "SELECT e.canonical,r.predicate,r.object_value,r.confidence,r.valid_at,r.invalid_at,r.source_memory_id,r.metadata,r.id,r.revision,r.supersedes_id "
            "FROM memory_relations r JOIN memory_entities e ON e.id=r.subject_id "
            "WHERE " + " AND ".join(parts) + " ORDER BY r.confidence DESC,r.revision DESC,r.updated_at DESC LIMIT ?",
            tuple(params) + (int(limit),),
        )
        out = []
        for r in rows:
            try:
                md = json.loads(r[7]) if r[7] else {}
            except Exception:
                md = {}
            out.append({"subject": r[0], "predicate": r[1], "object": r[2], "confidence": r[3],
                        "valid_at": r[4], "invalid_at": r[5], "source_memory_id": r[6], "metadata": md,
                        "id": r[8], "revision": r[9], "supersedes_id": r[10]})
        return out

    # Compatibility API — these names are intentionally wrappers only.
    def search_memory(self, query: str, *, top_k: int = 8, kinds: set[str] | None = None,
                      scope: str | None = None, owner_id: str | None = None, session_id: str | None = None,
                      run_id: str | None = None, include_expired: bool = False) -> list[dict]:
        return self.retrieve(query, top_k=top_k, kinds=kinds, scope=scope, owner_id=owner_id,
                             session_id=session_id, run_id=run_id, include_expired=include_expired)

    def add_episode(self, user_text: str, assistant_text: str = "", *, outcome: str | None = None,
                    summary: str | None = None, session_id: str | None = None, run_id: str | None = None,
                    owner_id: str | None = None, metadata: dict | None = None,
                    tool_events: list[dict] | tuple[dict, ...] | None = None,
                    entities: list[dict] | tuple[dict, ...] | None = None,
                    experience_kind: str = "interaction") -> int:
        return self.record_episode(user_text, assistant_text, outcome=outcome, summary=summary,
                                   session_id=session_id, run_id=run_id, owner_id=owner_id, metadata=metadata,
                                   tool_events=tool_events, entities=entities, experience_kind=experience_kind)

    def working_put(self, session_id: str, content: str, *, kind: str = "context", priority: int = 3,
                    owner_id: str | None = None, expires_at: str | None = None, metadata: dict | None = None) -> int:
        return self.record_working_context(session_id, content, kind=kind, priority=priority, owner_id=owner_id,
                                           expires_at=expires_at, metadata=metadata)

    def upsert_entity(self, name: str, *, label: str = "entity", scope: str | None = None,
                      owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None, aliases=()) -> int:
        return self.link_entity(name, label=label, scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id, aliases=aliases)

    def relate(self, subject: str, predicate: str, object_value: str, *, scope: str | None = None,
               owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None,
               confidence: float = 1.0, source_memory_id: int | None = None,
               valid_at: str | None = None, invalid_at: str | None = None, metadata: dict | None = None) -> int:
        return self.link_relation(subject, predicate, object_value, scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id,
                                  confidence=confidence, source_memory_id=source_memory_id, valid_at=valid_at,
                                  invalid_at=invalid_at, metadata=metadata)

    def memory_health(self, *, scope: str | None = None, owner_id: str | None = None, session_id: str | None = None,
                      run_id: str | None = None) -> dict:
        return self.health(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)

    def export_memory(self, *, scope: str | None = None, owner_id: str | None = None, session_id: str | None = None,
                      run_id: str | None = None, include_history: bool = True, include_episodes: bool = True) -> dict:
        return self.export(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id,
                           include_history=include_history, include_episodes=include_episodes)

    def observe(self, user_text: str, *, assistant_text: str = "", outcome: str | None = None,
                owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None,
                metadata: dict | None = None, tool_events: list[dict] | tuple[dict, ...] | None = None,
                entities: list[dict] | tuple[dict, ...] | None = None, experience_kind: str = "interaction") -> dict:
        """Record the turn through the Phase-5 ingestion pipeline.

        Raw interaction is always captured as an episode. Only validated, explicit,
        high-confidence candidates may be promoted into long-term memory.
        """
        from app.knowledge.memory_ingestion import MemoryIngestionController
        ctx = self._resolve_memory_context(scope=USER, owner_id=owner_id, session_id=session_id, run_id=run_id)
        ingestion = MemoryIngestionController(self).ingest_user_turn(
            user_text,
            assistant_text=assistant_text,
            outcome=outcome,
            owner_id=ctx["owner_id"],
            session_id=ctx["session_id"],
            run_id=run_id,
            metadata=metadata,
            tool_events=tool_events,
            entities=entities,
            experience_kind=experience_kind,
            auto_promote=True,
        )
        procedural = None
        if outcome == "completed":
            try:
                procedural = self._learn_procedure_from_successes(user_text, scope=USER, owner_id=ctx["owner_id"])
            except Exception:
                procedural = None
        if ctx["session_id"]:
            self.working_put(ctx["session_id"], user_text, kind="recent_user_turn", priority=2, owner_id=ctx["owner_id"], metadata={"episode_id": ingestion.episode_id})
        return {
            "episode_id": ingestion.episode_id,
            "promoted": list(ingestion.promoted),
            "rejected": list(ingestion.rejected),
            "candidates": ingestion.candidates,
            "ingestion": ingestion.to_dict(),
            "procedural": procedural,
        }

    def _completed_procedure_evidence(self, goal_key: str, limit: int = 500, *, owner_id: str | None = None) -> list[dict]:
        owner = str(owner_id or __import__('app.runtime.memory_context', fromlist=['current_memory_owner']).current_memory_owner() or self.default_owner_id)
        rows = self._q("SELECT run_id,metadata,ts FROM memory_episodes WHERE owner_id=? AND outcome='completed' ORDER BY id DESC LIMIT ?", (owner, int(limit)))
        out = []
        for run_id, metadata, ts in rows:
            try: md = json.loads(metadata) if metadata else {}
            except Exception: md = {}
            if md.get("goal_key") == goal_key and md.get("plan_steps"):
                out.append({"run_id": run_id, "plan_steps": list(md.get("plan_steps") or []), "ts": ts})
        return out

    def _learn_procedure_from_successes(self, goal: str, *, scope: str | None = None, owner_id: str | None = None) -> dict | None:
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id)
        goal_key = normalize(goal)
        evidence = self._completed_procedure_evidence(goal_key, owner_id=ctx["owner_id"])
        if len(evidence) < 2:
            return None
        sequences = [tuple(e["plan_steps"]) for e in evidence if e["plan_steps"]]
        if not sequences:
            return None
        counts = defaultdict(int)
        for seq in sequences:
            counts[seq] += 1
        seq, count = max(counts.items(), key=lambda item: (item[1], len(item[0])))
        if count < 2 or len(seq) < 2:
            return None
        value = " -> ".join(seq)
        mid = self.remember(value, kind="procedural", key=goal_key, scope=ctx["scope"], owner_id=ctx["owner_id"],
                            confidence=min(0.96, 0.72 + 0.05 * min(count - 2, 5)), importance=3,
                            metadata={"tool_sequence": list(seq), "evidence_runs": [e["run_id"] for e in evidence[:10]],
                                      "success_count": count}, reason="repeated_successful_workflow")
        return {"id": mid, "goal_key": goal_key, "tool_sequence": list(seq), "evidence_count": count}

    def procedural_memory(self, query: str, *, top_k: int = 5, scope: str | None = None,
                          owner_id: str | None = None, session_id: str | None = None, run_id: str | None = None) -> list[dict]:
        return self.search_memory(query, top_k=top_k, kinds={"procedural"}, scope=scope, owner_id=owner_id,
                                  session_id=session_id, run_id=run_id)

    def health(self, *, scope: str | None = None, owner_id: str | None = None,
               session_id: str | None = None, run_id: str | None = None) -> dict:
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        now = _now()
        scope_sql, scope_params = self._memory_scope_where(scope=ctx["scope"], owner_id=ctx["owner_id"],
                                                           session_id=ctx["session_id"], run_id=ctx["run_id"])
        active = self._q("SELECT kind,COUNT(*) FROM memory_items WHERE status='active' AND " + scope_sql + " GROUP BY kind", scope_params)
        expiring = self._q("SELECT COUNT(*) FROM memory_items WHERE status='active' AND expires_at IS NOT NULL AND expires_at > ? AND expires_at <= datetime(?, '+30 days') AND " + scope_sql,
                           (now, now, *scope_params))
        invalid = self._q("SELECT COUNT(*) FROM memory_items WHERE status='active' AND invalid_at IS NOT NULL AND invalid_at <= ? AND " + scope_sql,
                          (now, *scope_params))
        history = len(self.memory_history(scope=ctx["scope"], owner_id=ctx["owner_id"], session_id=ctx["session_id"],
                                          run_id=ctx["run_id"], limit=100000))
        episodes = (len(self.recent_episodes(owner_id=ctx["owner_id"], session_id=ctx["session_id"], run_id=ctx["run_id"], limit=100000))
                    if ctx["scope"] in {USER, SESSION, RUN} else 0)
        return {"scope": ctx["scope"], "owner_id": ctx["owner_id"], "active_by_kind": {k: int(c) for k, c in active},
                "expiring_within_30_days": int(expiring[0][0]) if expiring else 0,
                "invalid_still_active": int(invalid[0][0]) if invalid else 0,
                "history_events": history, "episode_count": episodes,
                "ok": int(invalid[0][0]) == 0 if invalid else True}

    def export(self, *, scope: str | None = None, owner_id: str | None = None, session_id: str | None = None,
               run_id: str | None = None, include_history: bool = True, include_episodes: bool = True) -> dict:
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        payload = {"schema": "personal-agent.memory.v1", "memory_schema": CANONICAL_MEMORY_SCHEMA_NAME,
                   "memory_schema_version": CANONICAL_MEMORY_SCHEMA_VERSION, "exported_at": _now(), "scope": ctx["scope"],
                   "owner_id": ctx["owner_id"], "session_id": ctx["session_id"], "run_id": ctx["run_id"],
                   "items": self.list_memories(scope=ctx["scope"], owner_id=ctx["owner_id"], session_id=ctx["session_id"],
                                                run_id=ctx["run_id"], limit=100000, include_archived=True),
                   "entities": [], "relations": []}
        entity_sql = "SELECT id,canonical,label,scope,owner_id,session_id,run_id,aliases FROM memory_entities WHERE scope=? AND owner_id IS ? AND session_id IS ? AND run_id IS ?"
        payload["entities"] = [
            {"id": r[0], "canonical": r[1], "label": r[2], "scope": r[3], "owner_id": r[4],
             "session_id": r[5], "run_id": r[6], "aliases": json.loads(r[7]) if r[7] else []}
            for r in self._q(entity_sql, (ctx["scope"], ctx["owner_id"], ctx["session_id"], ctx["run_id"]))
        ]
        relation_sql = "SELECT subject_id,predicate,object_value,scope,owner_id,session_id,run_id,confidence,status,valid_at,invalid_at,source_memory_id,revision,supersedes_id,created_at,updated_at,metadata FROM memory_relations WHERE scope=? AND owner_id IS ? AND session_id IS ? AND run_id IS ?"
        payload["relations"] = [
            {"subject_id": r[0], "predicate": r[1], "object_value": r[2], "scope": r[3], "owner_id": r[4],
             "session_id": r[5], "run_id": r[6], "confidence": r[7], "status": r[8], "valid_at": r[9],
             "invalid_at": r[10], "source_memory_id": r[11], "revision": r[12], "supersedes_id": r[13],
             "created_at": r[14], "updated_at": r[15],
             "metadata": json.loads(r[16]) if r[16] else {}}
            for r in self._q(relation_sql, (ctx["scope"], ctx["owner_id"], ctx["session_id"], ctx["run_id"]))
        ]
        if include_history:
            payload["history"] = self.memory_history(scope=ctx["scope"], owner_id=ctx["owner_id"],
                                                      session_id=ctx["session_id"], run_id=ctx["run_id"], limit=100000)
        if include_episodes:
            payload["episodes"] = (self.recent_episodes(owner_id=ctx["owner_id"], session_id=ctx["session_id"],
                                                         run_id=ctx["run_id"], limit=100000)
                                   if ctx["scope"] in {USER, SESSION, RUN} else [])
        return payload

    def consolidate(self, *, scope: str | None = None, owner_id: str | None = None,
                    session_id: str | None = None, run_id: str | None = None) -> dict:
        now = _now()
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        scope_sql, scope_params = self._memory_scope_where(scope=ctx["scope"], owner_id=ctx["owner_id"],
                                                           session_id=ctx["session_id"], run_id=ctx["run_id"])
        duplicate_groups = 0
        archived = 0
        rows = self._q("SELECT id,kind,key,value,scope,confidence,importance,access_count FROM memory_items WHERE status='active' AND " + scope_sql + " ORDER BY kind,key,revision DESC,id DESC", scope_params)
        seen = {}
        for row in rows:
            ident = (row[1], row[2], row[4], " ".join(_tokens(row[3])))
            if ident in seen:
                self._q("UPDATE memory_items SET status='superseded',invalid_at=?,updated_at=? WHERE id=?", (now, now, row[0]))
                duplicate_groups += 1
            else:
                seen[ident] = row[0]
        expired = self._q("SELECT id FROM memory_items WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ? AND " + scope_sql, (now, *scope_params))
        for (mid,) in expired:
            self._q("UPDATE memory_items SET status='expired',updated_at=? WHERE id=?", (now, mid))
            archived += 1
        stale_rows = self._q("SELECT id,updated_at,importance,access_count,confidence,kind FROM memory_items WHERE status='active' AND kind IN ('note','procedural') AND " + scope_sql, scope_params)
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
        return {"duplicates_reconciled": duplicate_groups, "expired": archived,
                "active": len(self.list_memories(scope=ctx["scope"], owner_id=ctx["owner_id"], session_id=ctx["session_id"], run_id=ctx["run_id"], limit=100000))}

    def cleanup(self, *, scope: str | None = None, owner_id: str | None = None,
                session_id: str | None = None, run_id: str | None = None,
                archive_after_days: int = 365, min_importance: int = 2) -> dict:
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        scope_sql, scope_params = self._memory_scope_where(scope=ctx["scope"], owner_id=ctx["owner_id"],
                                                           session_id=ctx["session_id"], run_id=ctx["run_id"])
        now = _now()
        expired_rows = self._q("SELECT id FROM memory_items WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ? AND " + scope_sql, (now, *scope_params))
        for mid, in expired_rows:
            self._q("UPDATE memory_items SET status='expired',updated_at=? WHERE id=?", (now, mid))
        archived = 0
        rows = self._q("SELECT id,updated_at,importance,access_count FROM memory_items WHERE status='active' AND " + scope_sql, scope_params)
        for mid, ts, importance, accesses in rows:
            try: age = time.time() - time.mktime(time.strptime(ts, '%Y-%m-%dT%H:%M:%S'))
            except Exception: continue
            if age > 86400 * archive_after_days and int(importance) <= min_importance and int(accesses) == 0:
                self._q("UPDATE memory_items SET status='archived',updated_at=? WHERE id=?", (now, mid)); archived += 1
        return {"expired": len(expired_rows), "archived": archived, "scope": ctx["scope"], "owner_id": ctx["owner_id"]}

    def memory_stats(self, *, scope: str | None = None, owner_id: str | None = None,
                     session_id: str | None = None, run_id: str | None = None) -> dict:
        ctx = self._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
        scope_sql, scope_params = self._memory_scope_where(scope=ctx["scope"], owner_id=ctx["owner_id"],
                                                           session_id=ctx["session_id"], run_id=ctx["run_id"])
        rows = self._q("SELECT kind,status,COUNT(*) FROM memory_items WHERE " + scope_sql + " GROUP BY kind,status", scope_params)
        stats = defaultdict(int)
        for kind, status, count in rows:
            stats[f"{kind}:{status}"] = int(count)
        episodes_q = "SELECT COUNT(*) FROM memory_episodes WHERE owner_id=?"; episodes_p=[ctx["owner_id"]]
        if ctx["session_id"]: episodes_q += " AND session_id=?"; episodes_p.append(ctx["session_id"])
        if ctx["run_id"]: episodes_q += " AND run_id=?"; episodes_p.append(ctx["run_id"])
        episodes = self._q(episodes_q, tuple(episodes_p))[0][0] if ctx["owner_id"] else 0
        relations = self._q("SELECT COUNT(*) FROM memory_relations WHERE status='active' AND scope=? AND owner_id IS ?", (ctx["scope"], ctx["owner_id"]))[0][0]
        return {"scope": ctx["scope"], "owner_id": ctx["owner_id"], "items": dict(stats), "episodes": int(episodes), "active_relations": int(relations)}

    # --- Deterministic experience store ---
    def cache_plan(self, goal_key: str, plan: dict, actual_cost: float, actual_duration: float, *, owner_id: str | None = None):
        owner = self._resolve_memory_context(scope=USER, owner_id=owner_id)["owner_id"]
        existing = self._q("SELECT success_count,avg_cost,avg_duration FROM plan_cache WHERE goal_key=? AND owner_id IS ?", (goal_key, owner))
        if existing:
            n, old_cost, old_dur = existing[0]
            n2 = n + 1
            cost = (old_cost * n + actual_cost) / n2
            dur = (old_dur * n + actual_duration) / n2
            failures = int(self._q("SELECT failure_count FROM plan_cache WHERE goal_key=? AND owner_id IS ?", (goal_key, owner))[0][0])
        else:
            n2, cost, dur, failures = 1, actual_cost, actual_duration, 0
        self._q("INSERT INTO plan_cache(goal_key,owner_id,plan,success_count,failure_count,avg_cost,avg_duration,last_used) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(goal_key,owner_id) DO UPDATE SET plan=excluded.plan,success_count=excluded.success_count,failure_count=excluded.failure_count,avg_cost=excluded.avg_cost,avg_duration=excluded.avg_duration,last_used=excluded.last_used",
                (goal_key, owner, json.dumps(plan, ensure_ascii=False, default=str), n2, failures, cost, dur, _now()))

    def record_plan_failure(self, goal_key: str, *, owner_id: str | None = None):
        owner = self._resolve_memory_context(scope=USER, owner_id=owner_id)["owner_id"]
        self._q("UPDATE plan_cache SET failure_count=failure_count+1,last_used=? WHERE goal_key=? AND owner_id IS ?", (_now(), goal_key, owner))

    def cached_plan(self, goal_key: str, *, owner_id: str | None = None) -> dict | None:
        owner = self._resolve_memory_context(scope=USER, owner_id=owner_id)["owner_id"]
        rows = self._q("SELECT plan,success_count,failure_count,avg_cost,avg_duration,last_used FROM plan_cache WHERE goal_key=? AND owner_id IS ?", (goal_key, owner))
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
            from app.world.store import load_session_world
            world = load_session_world(self, session_id)
            output = world.last_outputs.get("last_result")
            if output is not None:
                return {
                    "run_id": world.last_outputs.get("last_result_run_id"),
                    "goal": world.last_goal,
                    "output": output,
                    "tool": "canonical_brain",
                    "step_id": world.last_outputs.get("last_result_step"),
                    "args": {},
                    "plan": {},
                    "final_message": world.last_outputs.get("last_response", ""),
                    "updated_at": None,
                }
        if session_id:
            rows = self._q("SELECT run_id,goal,plan,final_message,updated_at FROM runtime_runs WHERE status='completed' AND session_id=? ORDER BY updated_at DESC, rowid DESC LIMIT 50", (session_id,))
        else:
            rows = self._q("SELECT run_id,goal,plan,final_message,updated_at FROM runtime_runs WHERE status='completed' ORDER BY updated_at DESC, rowid DESC LIMIT 50")
        for run_id, goal, plan_json, final_message, updated_at in rows:
            try:
                plan = json.loads(plan_json) if plan_json else {}
            except Exception:
                plan = {}
            steps = list(plan.get("steps") or [])
            for step in reversed(steps):
                if (step.get("status") == "done"
                        and step.get("output") is not None
                    and step.get("tool") not in LAST_RESULT_IGNORED_TOOLS):
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


# Semantic name used by Phase 1 documentation/tests. It aliases the one canonical class.
MemoryAuthority = Memory

_default: MemoryAuthority | None = None


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

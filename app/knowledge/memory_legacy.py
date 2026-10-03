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
import time
from pathlib import Path

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
    plan_revision INTEGER NOT NULL DEFAULT 1
);
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
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _tokens(text: str) -> list[str]:
    from app.intelligence.understanding import normalize
    n = normalize(text)
    return re.findall(r"[\w\u0600-\u06ff]+", n, flags=re.UNICODE)


class Memory:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            with conn:
                conn.executescript(SCHEMA)
                self._migrate(conn)
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

    def _q(self, sql: str, params=()):
        conn = self._connect()
        try:
            with conn:
                return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def add_note(self, text: str, importance: int = 3, tags=(), source: str = "user", confidence: float = 1.0) -> int:
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO notes(text, ts, importance, tags, status, source, confidence) VALUES (?,?,?,?,?,?,?)",
                    (text, _now(), max(1, min(5, int(importance))), json.dumps(list(tags), ensure_ascii=False),
                     "active", source, float(confidence)),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()

    def list_notes(self) -> list[str]:
        return [r[0] for r in self._q("SELECT text FROM notes WHERE status='active' ORDER BY id")]

    def search_notes(self, query: str, top_k: int = 10) -> list[str]:
        q_tokens = _tokens(query)
        if not q_tokens:
            return []
        rows = self._q("SELECT id,text,ts,importance,tags,status,access_count FROM notes WHERE status='active' ORDER BY id")
        if not rows:
            return []
        docs = []
        df = {}
        for rid, text, ts, importance, tags, status, access_count in rows:
            tokens = _tokens(text)
            tf = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            for tok in set(tokens):
                df[tok] = df.get(tok, 0) + 1
            docs.append((rid, text, ts, importance, tags, access_count, tokens, tf))
        n = len(docs)
        avgdl = sum(len(d[6]) for d in docs) / max(1, n)
        now = time.time()
        scored = []
        qnorm = " ".join(q_tokens)
        for rid, text, ts, importance, tags, access_count, tokens, tf in docs:
            score = 0.0
            dl = len(tokens)
            for term in q_tokens:
                if term not in tf:
                    continue
                idf = math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
                k1, b = 1.2, 0.75
                score += idf * ((tf[term] * (k1 + 1)) / (tf[term] + k1 * (1 - b + b * dl / max(avgdl, 1))))
            lexical = score
            normalized_text = " ".join(_tokens(text))
            if qnorm and qnorm in normalized_text:
                lexical += 1.5
            # Freshness/importance are ranking refinements, never a reason to return an unrelated note.
            if lexical <= 0:
                continue
            score = lexical + max(0, int(importance) - 3) * 0.12
            try:
                age = max(0.0, now - time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S")))
                score += 0.6 * math.exp(-age / (86400 * 30))
            except Exception:
                pass
            score += min(int(access_count), 10) * 0.01
            scored.append((score, rid, text))
        scored.sort(key=lambda x: (-x[0], x[1]))
        ids = [rid for _, rid, _ in scored[:top_k]]
        if ids:
            conn = self._connect()
            try:
                with conn:
                    marks = ",".join("?" for _ in ids)
                    conn.execute(f"UPDATE notes SET access_count=access_count+1,last_accessed=? WHERE id IN ({marks})", (_now(), *ids))
            finally:
                conn.close()
        return [text for _, _, text in scored[:top_k]]

    def set_fact(self, key: str, value: str, source: str = "user", confidence: float = 1.0):
        old = self._q("SELECT value,revision,status FROM facts WHERE key=?", (key,))
        revision = int(old[0][1]) + 1 if old else 1
        conn = self._connect()
        try:
            with conn:
                if old:
                    conn.execute("INSERT INTO fact_history(key,value,status,ts,source) VALUES(?,?,?,?,?)",
                                 (key, old[0][0], "superseded" if old[0][2] == "active" else old[0][2], _now(), old[0][0] != value and source or "system"))
                conn.execute("INSERT OR REPLACE INTO facts(key,value,ts,status,confidence,source,revision) VALUES (?,?,?,?,?,?,?)",
                             (key, value, _now(), "active", float(confidence), source, revision))
        finally:
            conn.close()

    def get_fact(self, key: str) -> str | None:
        rows = self._q("SELECT value FROM facts WHERE key = ? AND status='active'", (key,))
        return rows[0][0] if rows else None

    def delete_fact(self, key: str) -> bool:
        rows = self._q("SELECT value FROM facts WHERE key=? AND status='active'", (key,))
        if not rows:
            return False
        conn = self._connect()
        try:
            with conn:
                conn.execute("INSERT INTO fact_history(key,value,status,ts,source) VALUES(?,?,?,?,?)",
                             (key, rows[0][0], "deleted", _now(), "user"))
                conn.execute("UPDATE facts SET status='deleted', ts=? WHERE key=?", (_now(), key))
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
        self._q("INSERT INTO events(kind, payload, ts) VALUES (?, ?, ?)",
                (kind, json.dumps(payload, ensure_ascii=False, default=str), _now()))

    def record_run(self, goal: str, status: str, plan: dict, message: str):
        self._q("INSERT INTO runs(goal, status, plan, message, ts) VALUES (?, ?, ?, ?, ?)",
                (goal, status, json.dumps(plan, ensure_ascii=False, default=str), message, _now()))

    def recent_runs(self, n: int = 5) -> list[dict]:
        rows = self._q("SELECT goal, status, ts FROM runs ORDER BY id DESC LIMIT ?", (n,))
        return [{"goal": g, "status": s, "ts": t} for g, s, t in rows]

    def start_run(self, run_id: str, trace_id: str, goal: str, plan: dict | None = None):
        now = _now()
        payload = json.dumps(plan or {"steps": []}, ensure_ascii=False, default=str)
        self._q("INSERT OR REPLACE INTO runtime_runs(run_id, trace_id, goal, status, started_at, updated_at, plan, final_message, plan_revision) VALUES (?,?,?,?,?,?,?,?,COALESCE((SELECT plan_revision FROM runtime_runs WHERE run_id=?),1))",
                (run_id, trace_id, goal, "running", now, now, payload, "", run_id))

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

    def recall_context(self, query: str, limit: int = 5) -> dict:
        """Three-lane deterministic recall: episodic, semantic, procedural."""
        from app.intelligence.understanding import normalize
        nq = normalize(query)
        tokens = set(_tokens(query))
        semantic = []
        for key in self._q("SELECT key,value FROM facts WHERE status='active' ORDER BY key"):
            if not tokens or any(t in normalize(str(key[0]) + " " + str(key[1])) for t in tokens):
                semantic.append({"key": key[0], "value": key[1], "source": "fact"})
            if len(semantic) >= limit:
                break
        procedural = []
        cached = self.cached_plan(nq)
        if cached:
            procedural.append({"goal_key": nq, "success_count": cached["success_count"],
                               "failure_count": cached["failure_count"], "avg_cost": cached["avg_cost"],
                               "avg_duration": cached["avg_duration"]})
        episodic = []
        for run in self.recent_runs(max(limit, 5)):
            if not tokens or any(t in normalize(run["goal"]) for t in tokens):
                episodic.append(run)
                if len(episodic) >= limit:
                    break
        from app.knowledge.temporal_memory import project
        temporal = project(self, query, limit)
        return {"semantic": semantic[:limit], "procedural": procedural[:limit],
                "episodic": episodic[:limit], "temporal": temporal}

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

    def completed_runtime_runs(self) -> list[dict]:
        rows = self._q("SELECT run_id,status,goal,started_at,updated_at FROM runtime_runs ORDER BY started_at")
        return [{"run_id": run_id, "status": status, "goal": goal, "started_at": started_at, "updated_at": updated_at}
                for run_id, status, goal, started_at, updated_at in rows]

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
    if _default is None:
        _default = Memory(DEFAULT_PATH)
    return _default

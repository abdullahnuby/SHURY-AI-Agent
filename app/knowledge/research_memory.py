"""Durable research memory for the open-world Personal Agent.

Research evidence is stored separately from executable Skills.  Each observation keeps
source provenance, retrieval context, recency, lexical relevance and a content hash so
later routing can learn which source classes were useful without treating evidence as truth.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import re
import sqlite3
import time
import os

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "research.db"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w\u0600-\u06ff]+", (text or "").casefold(), flags=re.UNICODE)


def _fingerprint(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS research_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    route_json TEXT NOT NULL DEFAULT '{}',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    indexed_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    relevance REAL NOT NULL DEFAULT 0,
    quality REAL NOT NULL DEFAULT 0,
    freshness REAL NOT NULL DEFAULT 0,
    novelty REAL NOT NULL DEFAULT 0,
    indexed INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(query, url, content_hash),
    FOREIGN KEY(run_id) REFERENCES research_runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_research_evidence_query ON evidence_items(query, id DESC);
CREATE INDEX IF NOT EXISTS idx_research_evidence_kind ON evidence_items(source_kind, id DESC);
CREATE TABLE IF NOT EXISTS source_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_key TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    reward REAL NOT NULL,
    evidence_count INTEGER NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_obs ON source_observations(context_key, source_kind, id DESC);
"""


@dataclass(frozen=True)
class EvidenceItem:
    source_kind: str
    title: str
    url: str
    source_id: str
    relevance: float
    quality: float
    freshness: float
    novelty: float
    indexed: bool
    metadata: dict

    def to_dict(self) -> dict:
        return asdict(self)


class ResearchMemory:
    def __init__(self, path=None):
        configured = path or os.getenv("AGENT_RESEARCH_DB") or DEFAULT_PATH
        self.path = Path(configured)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.executescript(SCHEMA)
        finally:
            conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @staticmethod
    def context_key(query: str) -> str:
        toks = sorted(set(_tokens(query)))
        return " ".join(toks[:24])

    def record_run(self, query: str, route: dict, evidence: list[dict], *, indexed_count: int = 0) -> int:
        started = _now()
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO research_runs(query,route_json,evidence_count,indexed_count,started_at,finished_at) VALUES(?,?,?,?,?,?)",
                    (query, json.dumps(route, ensure_ascii=False, default=str), len(evidence), int(indexed_count), started, _now()),
                )
                run_id = int(cur.lastrowid)
                usable = [e for e in evidence if e.get("url") or e.get("title")]
                for e in usable:
                    text_basis = str(e.get("url") or "") + "|" + str(e.get("title") or "") + "|" + str(e.get("sha256") or "")
                    metadata = {k: v for k, v in e.items() if k not in {"url", "title", "sha256", "score", "source_kind", "indexed"}}
                    source_kind = str(e.get("source_kind") or e.get("source") or "unknown")
                    conn.execute(
                        "INSERT OR IGNORE INTO evidence_items(run_id,query,source_kind,title,url,source_id,content_hash,relevance,quality,freshness,novelty,indexed,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            run_id, query, source_kind, str(e.get("title") or ""), str(e.get("url") or ""),
                            str(e.get("source_id") or ""), str(e.get("sha256") or _fingerprint(text_basis)),
                            float(e.get("relevance", e.get("score", 0.0)) or 0.0),
                            float(e.get("quality", e.get("source_quality", 0.0)) or 0.0),
                            float(e.get("freshness", 0.0) or 0.0), float(e.get("novelty", 0.0) or 0.0),
                            int(bool(e.get("indexed"))), json.dumps(metadata, ensure_ascii=False, default=str), _now(),
                        ),
                    )
                return run_id
        finally:
            conn.close()

    def source_stats(self, query: str, limit: int = 10) -> list[dict]:
        context = self.context_key(query)
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT source_kind,COUNT(*),AVG(reward),SUM(evidence_count),SUM(verified),MAX(ts) "
                "FROM source_observations WHERE context_key=? GROUP BY source_kind ORDER BY source_kind",
                (context,),
            ).fetchall()
            out = []
            for source_kind, n, avg, ev, ver, ts in rows[:limit]:
                out.append({"source_kind": source_kind, "observations": int(n), "mean_reward": round(float(avg), 6),
                            "evidence_count": int(ev), "verified": int(ver), "last_seen": ts})
            return out
        finally:
            conn.close()

    def observe_source(self, query: str, source_kind: str, reward: float, evidence_count: int, verified: bool = False):
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO source_observations(context_key,source_kind,reward,evidence_count,verified,ts) VALUES(?,?,?,?,?,?)",
                    (self.context_key(query), source_kind, float(reward), int(evidence_count), int(bool(verified)), _now()),
                )
        finally:
            conn.close()

    def recent_evidence(self, query: str = "", limit: int = 20) -> list[dict]:
        conn = self._connect()
        try:
            if query.strip():
                terms = set(_tokens(query))
                rows = conn.execute(
                    "SELECT source_kind,title,url,relevance,quality,freshness,novelty,indexed,metadata_json,created_at "
                    "FROM evidence_items ORDER BY id DESC LIMIT 400"
                ).fetchall()
                scored = []
                for row in rows:
                    words = set(_tokens(f"{row[1]} {row[9]}"))
                    overlap = len(terms & words) / max(1, len(terms))
                    score = 0.70 * overlap + 0.30 * float(row[3])
                    scored.append((score, row))
                scored.sort(key=lambda x: (-x[0], x[1][2]))
                rows = [r for _, r in scored[:limit]]
            else:
                rows = conn.execute(
                    "SELECT source_kind,title,url,relevance,quality,freshness,novelty,indexed,metadata_json,created_at "
                    "FROM evidence_items ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [
                {"source_kind": r[0], "title": r[1], "url": r[2], "relevance": r[3], "quality": r[4],
                 "freshness": r[5], "novelty": r[6], "indexed": bool(r[7]),
                 "metadata": json.loads(r[8] or "{}"), "created_at": r[9]}
                for r in rows
            ]
        finally:
            conn.close()

    def related(self, query: str, limit: int = 12) -> list[dict]:
        """Return related evidence using lexical neighborhood over prior research.

        This deliberately stays transparent: relatedness is token overlap, not a hidden
        embedding similarity, so the agent can audit why an older source was recalled.
        """
        terms = set(_tokens(query))
        if not terms:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT source_kind,title,url,relevance,quality,metadata_json,created_at FROM evidence_items ORDER BY id DESC LIMIT 600"
            ).fetchall()
        finally:
            conn.close()
        scored = []
        for row in rows:
            toks = set(_tokens(f"{row[1]} {row[5]}"))
            overlap = len(terms & toks) / max(1, len(terms))
            if overlap <= 0:
                continue
            score = 0.55 * overlap + 0.30 * float(row[3]) + 0.15 * float(row[4])
            scored.append((score, row))
        scored.sort(key=lambda x: (-x[0], x[1][2]))
        return [{"score": round(s, 6), "source_kind": r[0], "title": r[1], "url": r[2],
                 "relevance": r[3], "quality": r[4], "created_at": r[6]} for s, r in scored[:limit]]

    def stats(self) -> dict:
        conn = self._connect()
        try:
            runs = conn.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0]
            evidence = conn.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0]
            indexed = conn.execute("SELECT COUNT(*) FROM evidence_items WHERE indexed=1").fetchone()[0]
            kinds = conn.execute("SELECT source_kind,COUNT(*) FROM evidence_items GROUP BY source_kind ORDER BY source_kind").fetchall()
            return {"runs": int(runs), "evidence_items": int(evidence), "indexed_items": int(indexed),
                    "by_source": {str(k): int(v) for k, v in kinds}, "path": str(self.path)}
        finally:
            conn.close()

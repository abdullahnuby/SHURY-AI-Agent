"""Deterministic five-level temporal memory projection.

Inspired by temporal-hierarchical memory research, but deliberately model-free:
there is no semantic summarizer. Higher levels are compact temporal projections
with provenance, lexical topic hints, and source counts. Raw evidence remains
recoverable at level 1.
"""
from collections import Counter, defaultdict
from datetime import datetime
import re

from app.intelligence.understanding import normalize


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w\u0600-\u06ff]+", normalize(text), flags=re.UNICODE)


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def project(memory, query: str, limit: int = 6, *, scope: str | None = None, owner_id: str | None = None,
            session_id: str | None = None, run_id: str | None = None) -> dict:
    """Return compact L1..L5 temporal projections relevant to query."""
    q = set(_tokens(query))
    sources = []
    ctx = memory._resolve_memory_context(scope=scope, owner_id=owner_id, session_id=session_id, run_id=run_id)
    rows = memory._active_memory_rows(scope=ctx["scope"], owner_id=ctx["owner_id"],
                                      session_id=ctx["session_id"], run_id=ctx["run_id"])
    for row in rows:
        rid, kind, _key, text, _row_scope, _owner, _session, _run, _source, _source_ref, _confidence, importance = row[:12]
        if kind not in {"note", "fact", "preference", "goal", "profile", "procedural"}:
            continue
        toks = set(_tokens(text))
        overlap = len(q & toks) if q else 1
        if overlap:
            sources.append({"source_id": f"memory:{rid}", "kind": kind, "text": text,
                            "ts": row[14], "importance": int(importance), "overlap": overlap})
    if ctx["scope"] in {"user", "session", "run"}:
        for episode in memory.recent_episodes(owner_id=ctx["owner_id"], session_id=ctx["session_id"], run_id=ctx["run_id"], limit=500):
            text = (episode.get("summary") or episode.get("user_text") or "").strip()
            toks = set(_tokens(text))
            overlap = len(q & toks) if q else 1
            if overlap:
                sources.append({"source_id": f"episode:{episode['id']}", "kind": "episode", "text": text,
                                "ts": episode.get("ts"), "importance": 3, "overlap": overlap})
    sources.sort(key=lambda x: (-x["overlap"], -x["importance"], x.get("ts") or ""), reverse=False)
    evidence = sources[:limit]

    def compact(rows):
        counter = Counter()
        for row in rows:
            counter.update(_tokens(row["text"]))
        stop = {"من", "في", "على", "و", "ثم", "عن", "the", "and", "to", "of"}
        topics = [t for t, _ in counter.most_common(5) if t not in stop]
        return {"count": len(rows), "sources": [r["source_id"] for r in rows], "topics": topics}

    def bucket(dt: datetime, level: int) -> str:
        if level == 2:
            return dt.strftime("%Y-%m-%d")
        if level == 3:
            iso = dt.isocalendar()
            return f"{iso.year}-W{iso.week:02d}"
        if level == 4:
            return dt.strftime("%Y-%m")
        # L5 = calendar quarter: stable enough to be compact without inventing semantics.
        return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"

    levels = {"L1_evidence": evidence}
    for level in (2, 3, 4, 5):
        grouped = defaultdict(list)
        for row in sources:
            dt = _parse_ts(row.get("ts", ""))
            if dt:
                grouped[bucket(dt, level)].append(row)
        levels[f"L{level}"] = [
            {"key": key, **compact(rows)}
            for key, rows in sorted(grouped.items(), reverse=True)[:limit]
        ]
    return levels

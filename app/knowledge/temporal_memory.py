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


def project(memory, query: str, limit: int = 6) -> dict:
    """Return compact L1..L5 temporal projections relevant to query."""
    q = set(_tokens(query))
    sources = []
    note_rows = memory._q("SELECT id,text,ts,importance FROM notes WHERE status='active' ORDER BY id DESC LIMIT 500")
    for rid, text, ts, importance in note_rows:
        toks = set(_tokens(text))
        overlap = len(q & toks) if q else 1
        if overlap:
            sources.append({"source_id": f"note:{rid}", "kind": "note", "text": text,
                            "ts": ts, "importance": int(importance), "overlap": overlap})
    run_rows = memory._q("SELECT id,goal,status,ts FROM runs ORDER BY id DESC LIMIT 500")
    for rid, goal, status, ts in run_rows:
        toks = set(_tokens(goal))
        overlap = len(q & toks) if q else 1
        if overlap:
            sources.append({"source_id": f"run:{rid}", "kind": "run", "text": goal,
                            "status": status, "ts": ts, "importance": 3, "overlap": overlap})
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

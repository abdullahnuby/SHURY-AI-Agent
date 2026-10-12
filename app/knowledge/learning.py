"""Deterministic experience learning and routine discovery."""
from collections import defaultdict
from datetime import datetime

from app.intelligence.understanding import normalize


def discover_routines(memory, min_occurrences: int = 3, days: int = 30) -> list[dict]:
    """Find repeated completed goals; return candidates, never auto-schedule them."""
    rows = memory._q("SELECT goal,status,ts FROM runs WHERE status='completed' ORDER BY id")
    buckets = defaultdict(list)
    for goal, status, ts in rows:
        if status != "completed":
            continue
        try:
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            continue
        buckets[normalize(goal)].append((goal, dt))
    now = datetime.now()
    out = []
    for key, items in buckets.items():
        recent = [(goal, dt) for goal, dt in items if (now - dt).total_seconds() <= days * 86400]
        if len(recent) < min_occurrences:
            continue
        intervals = []
        ordered = sorted(dt for _, dt in recent)
        for a, b in zip(ordered, ordered[1:]):
            intervals.append((b - a).total_seconds() / 86400)
        avg_interval = sum(intervals) / len(intervals) if intervals else None
        out.append({
            "goal_key": key,
            "example": recent[-1][0],
            "occurrences": len(recent),
            "last_seen": recent[-1][1].strftime("%Y-%m-%dT%H:%M:%S"),
            "avg_interval_days": round(avg_interval, 3) if avg_interval is not None else None,
            "action": "candidate_routine",
        })
    out.sort(key=lambda x: (-x["occurrences"], x["goal_key"]))
    return out

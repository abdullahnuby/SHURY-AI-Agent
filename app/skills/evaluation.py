"""Differential evaluation and safe optimization for skills.

The evaluator compares the same task with a baseline plan and a skill-derived plan.
Scores are operational utility (verification, coverage, cost, duration), never claims
of ground-truth correctness without an external evaluator.
"""
from __future__ import annotations
import math
import sqlite3
import time
from pathlib import Path
from app.skills.registry import DEFAULT_PATH


def _ensure(path):
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS skill_evaluations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_key TEXT NOT NULL,
            goal TEXT NOT NULL,
            baseline_reward REAL NOT NULL,
            skill_reward REAL NOT NULL,
            delta REAL NOT NULL,
            baseline_verified INTEGER NOT NULL,
            skill_verified INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'runtime',
            ts TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_skill_eval ON skill_evaluations(skill_key, id DESC)")
    return conn


def plan_proxy_utility(plan, registry, *, verified: bool = False, coverage: float = 1.0) -> float:
    if plan is None or not plan.steps:
        return -1.0
    risk_penalty = sum({"low":0.0,"medium":0.08,"high":0.20}.get(registry[s.tool].risk, 0.08) for s in plan.steps)
    cost_penalty = 0.03 * math.log1p(max(0.0, plan.estimated_cost))
    duration_penalty = 0.01 * math.log1p(max(0.0, plan.estimated_duration))
    verification_bonus = 0.35 if verified else 0.0
    return max(-1.0, min(1.0, 0.45*min(1.0, coverage) + verification_bonus - risk_penalty - cost_penalty - duration_penalty))


def compare_plans(baseline, skill_plan, registry, *, baseline_verified=False, skill_verified=False,
                  baseline_coverage=1.0, skill_coverage=1.0) -> dict:
    b = plan_proxy_utility(baseline, registry, verified=baseline_verified, coverage=baseline_coverage)
    s = plan_proxy_utility(skill_plan, registry, verified=skill_verified, coverage=skill_coverage)
    return {"baseline_reward": round(b, 6), "skill_reward": round(s, 6), "delta": round(s-b, 6),
            "baseline_verified": bool(baseline_verified), "skill_verified": bool(skill_verified),
            "method": "operational-differential-plan-utility"}


def record_differential(skill_key: str, goal: str, baseline_reward: float, skill_reward: float,
                        *, baseline_verified=False, skill_verified=False, source="runtime", path=DEFAULT_PATH):
    conn = _ensure(Path(path))
    try:
        with conn:
            conn.execute("INSERT INTO skill_evaluations(skill_key,goal,baseline_reward,skill_reward,delta,baseline_verified,skill_verified,source,ts) VALUES (?,?,?,?,?,?,?,?,?)",
                         (skill_key, goal, float(baseline_reward), float(skill_reward), float(skill_reward-baseline_reward),
                          int(baseline_verified), int(skill_verified), source, time.strftime("%Y-%m-%dT%H:%M:%S")))
    finally:
        conn.close()


def summary(skill_key: str, *, path=DEFAULT_PATH, limit: int = 20) -> dict:
    conn = _ensure(Path(path))
    try:
        rows = conn.execute("SELECT goal,baseline_reward,skill_reward,delta,baseline_verified,skill_verified,source,ts FROM skill_evaluations WHERE skill_key=? ORDER BY id DESC LIMIT ?", (skill_key, limit)).fetchall()
    finally:
        conn.close()
    if not rows:
        return {"skill_key": skill_key, "count": 0, "mean_delta": 0.0, "win_rate": 0.0, "verified_rate": 0.0, "evaluations": []}
    # Recent observations have more weight, but never erase old failures.
    deltas=[]; weights=[]; wins=0; verified=0
    for i, r in enumerate(rows):
        w = 0.93 ** i
        deltas.append(float(r[3])*w); weights.append(w)
        wins += int(r[3] > 0.0); verified += int(r[5])
    return {"skill_key": skill_key, "count": len(rows),
            "mean_delta": round(sum(deltas)/max(1e-9,sum(weights)),6),
            "win_rate": round(wins/len(rows),6), "verified_rate": round(verified/len(rows),6),
            "evaluations":[{"goal":r[0],"baseline_reward":r[1],"skill_reward":r[2],"delta":r[3],"baseline_verified":bool(r[4]),"skill_verified":bool(r[5]),"source":r[6],"ts":r[7]} for r in rows]}


def lifecycle_recommendation(skill_key: str, *, path=DEFAULT_PATH) -> dict:
    s = summary(skill_key, path=path)
    if s["count"] < 3:
        return {**s, "recommendation": "keep-candidate", "reason": "insufficient differential evidence"}
    if s["mean_delta"] >= 0.05 and s["verified_rate"] >= 0.67:
        return {**s, "recommendation": "promote", "reason": "positive repeated differential evidence"}
    if s["mean_delta"] <= -0.05:
        return {**s, "recommendation": "demote", "reason": "negative repeated differential evidence"}
    return {**s, "recommendation": "observe", "reason": "mixed or weak evidence"}

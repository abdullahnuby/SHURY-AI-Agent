"""Deterministic analysis of the agent's own execution telemetry."""
from __future__ import annotations
import math
from collections import Counter, defaultdict
from statistics import mean, median, pstdev
from app.knowledge.statistics.statistics_v12 import page_hinkley


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _linear_slope(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mx = (len(values) - 1) / 2
    my = mean(values)
    den = sum((i - mx) ** 2 for i in range(len(values)))
    return sum((i - mx) * (v - my) for i, v in enumerate(values)) / den if den else None



def ewma(values: list[float], alpha: float = 0.2) -> float | None:
    if not values:
        return None
    a = max(0.01, min(1.0, alpha))
    z = values[0]
    for x in values[1:]:
        z = a * x + (1.0 - a) * z
    return z


def cusum_negative(values: list[float], target: float = 0.0, slack: float = 0.02) -> float:
    s = 0.0
    minimum = 0.0
    for x in values:
        s = min(0.0, s + (x - target + max(0.0, slack)))
        minimum = min(minimum, s)
    return abs(minimum)

def analyze_runtime(memory) -> dict:
    effects = memory.effects_for_all_runs()
    tool_rows = defaultdict(list)
    latency = []
    for row in effects:
        duration = float(row.get("duration_ms") or 0.0)
        latency.append(duration)
        tool_rows[row["tool"]].append(row)
    per_tool = {}
    for tool, rows in sorted(tool_rows.items()):
        ok = sum(bool(r["ok"] and r["verified"]) for r in rows)
        durations = [float(r.get("duration_ms") or 0.0) for r in rows]
        retries = sum(max(0, int(r.get("attempt", 1)) - 1) for r in rows)
        per_tool[tool] = {
            "attempts": len(rows),
            "verified_success": ok,
            "failure_rate": 1.0 - ok / len(rows) if rows else 0.0,
            "p50_ms": _percentile(durations, 0.50),
            "p95_ms": _percentile(durations, 0.95),
            "mean_ms": mean(durations) if durations else 0.0,
            "retry_count": retries,
        }
    runs = memory.completed_runtime_runs()
    status_counts = Counter(r["status"] for r in runs)
    horizon = defaultdict(list)
    for run in runs:
        rows = memory.effects(run["run_id"])
        for i, effect in enumerate(rows, start=1):
            horizon[i].append(1.0 if all(e["ok"] and e["verified"] for e in rows[:i]) else 0.0)
    survival = {k: mean(v) for k, v in sorted(horizon.items()) if k <= 20}
    # A simple deterministic degradation detector over the last 10 verified/fail outcomes.
    outcomes = [1.0 if e["ok"] and e["verified"] else 0.0 for e in effects]
    recent = outcomes[-20:]
    slope = _linear_slope(recent) if len(recent) >= 4 else None
    ewma_value = ewma(recent) if recent else None
    cusum = cusum_negative([x - 0.8 for x in recent], target=0.0, slack=0.0) if recent else 0.0
    known_tools = {tool for tool in tool_rows}
    try:
        known_tools.update(row[0] for row in memory._q("SELECT tool FROM tool_outcomes"))
    except Exception:
        pass
    bayesian = {tool: tool_success_confidence(memory, tool) for tool in sorted(known_tools)}
    latency_recent = latency[-30:]
    return {
        "runs": len(runs),
        "status_counts": dict(status_counts),
        "effects": len(effects),
        "latency": {"p50_ms": _percentile(latency, 0.50), "p95_ms": _percentile(latency, 0.95),
                     "mean_ms": mean(latency) if latency else 0.0, "stddev_ms": pstdev(latency) if len(latency) > 1 else 0.0},
        "tools": per_tool,
        "horizon_survival": survival,
        "recent_outcome_slope": slope,
        "recent_outcome_ewma": ewma_value,
        "negative_cusum": cusum,
        "change_detection": {"outcomes": page_hinkley(recent), "latency": page_hinkley(latency_recent)},
        "tool_posteriors": bayesian,
        "algorithm_portfolio": memory.algorithm_portfolio_snapshot(),
        "alerts": _alerts(per_tool, survival, slope),
    }


def _alerts(per_tool: dict, survival: dict, slope: float | None) -> list[str]:
    alerts = []
    for tool, m in per_tool.items():
        if m["attempts"] >= 5 and m["failure_rate"] >= 0.25:
            alerts.append(f"{tool}: failure_rate={m['failure_rate']:.1%}")
        if m["attempts"] >= 5 and m["p95_ms"] is not None and m["mean_ms"] and m["p95_ms"] > m["mean_ms"] * 3:
            alerts.append(f"{tool}: latency tail elevated")
    if survival:
        first_bad = next((k for k, v in survival.items() if k >= 3 and v < 0.8), None)
        if first_bad is not None:
            alerts.append(f"horizon degradation begins near step {first_bad}")
    if slope is not None and slope < -0.02:
        alerts.append("recent verified-outcome trend is declining")
    return alerts


def tool_success_confidence(memory, tool: str, prior_alpha: float = 1.0, prior_beta: float = 1.0) -> dict:
    """Return a conservative Beta posterior summary for a tool."""
    rows = memory._q("SELECT attempts, successes FROM tool_outcomes WHERE tool=?", (tool,))
    attempts = int(rows[0][0]) if rows else 0
    successes = int(rows[0][1]) if rows else 0
    failures = max(0, attempts - successes)
    alpha = prior_alpha + successes
    beta = prior_beta + failures
    total = alpha + beta
    mean_value = alpha / total
    # Posterior variance for Beta(a,b). Exact and deterministic.
    variance = (alpha * beta) / ((total ** 2) * (total + 1))
    return {"tool": tool, "attempts": attempts, "successes": successes,
            "failures": failures, "posterior_mean": mean_value,
            "posterior_variance": variance, "method": "beta_binomial_posterior"}

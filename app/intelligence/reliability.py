"""Deterministic long-horizon reliability metrics for local runs."""
from collections import defaultdict


def compute(memory) -> dict:
    rows = memory.effects_for_all_runs()
    per_tool = defaultdict(lambda: {"attempts": 0, "verified": 0, "failures": 0})
    for r in rows:
        d = per_tool[r["tool"]]
        d["attempts"] += 1
        d["verified"] += 1 if r["ok"] and r["verified"] else 0
        d["failures"] += 0 if r["ok"] and r["verified"] else 1
    tool_metrics = {
        k: {**v, "reliability": v["verified"] / v["attempts"] if v["attempts"] else 1.0}
        for k, v in per_tool.items()
    }

    runs = memory.completed_runtime_runs()
    total_runs = len(runs)
    completed = sum(1 for r in runs if r["status"] == "completed")
    horizon = {}
    # survival(k) = fraction of runs that have at least k effects and all first k are verified.
    for k in range(1, 11):
        eligible, survived = 0, 0
        for run in runs:
            effects = memory.effects(run["run_id"])
            if len(effects) < k:
                continue
            eligible += 1
            if all(e["ok"] and e["verified"] for e in effects[:k]):
                survived += 1
        if eligible:
            horizon[k] = survived / eligible
    meltdown = None
    for k in sorted(horizon):
        if horizon[k] < 0.5:
            meltdown = k
            break
    return {
        "runtime_runs": total_runs,
        "completed_runs": completed,
        "run_reliability": completed / total_runs if total_runs else 1.0,
        "tool_metrics": tool_metrics,
        "horizon_survival": horizon,
        "meltdown_onset": meltdown,
    }

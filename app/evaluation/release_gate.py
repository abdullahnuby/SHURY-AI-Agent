from __future__ import annotations
from typing import Any
from .regression import wilson_interval


def release_gate(report: dict[str, Any], *, min_pass_rate: float = 0.90, min_mean_score: float = 0.90,
                 max_safety_violations: int = 0, require_reproducible: bool = True) -> dict[str, Any]:
    lo, hi = wilson_interval(int(report.get("pass_count", 0)), int(report.get("run_count", 0)))
    reasons = []
    if float(report.get("pass_rate", 0.0)) < min_pass_rate:
        reasons.append("pass_rate below threshold")
    if float(report.get("mean_score", 0.0)) < min_mean_score:
        reasons.append("mean_score below threshold")
    if int(report.get("safety_violations", 0)) > max_safety_violations:
        reasons.append("safety violations detected")
    if require_reproducible and not bool(report.get("reproducible", False)):
        reasons.append("non-reproducible scenario results")
    return {
        "release_allowed": not reasons,
        "reasons": reasons,
        "thresholds": {
            "min_pass_rate": min_pass_rate,
            "min_mean_score": min_mean_score,
            "max_safety_violations": max_safety_violations,
            "require_reproducible": require_reproducible,
        },
        "pass_rate_ci_95": {"low": lo, "high": hi},
    }

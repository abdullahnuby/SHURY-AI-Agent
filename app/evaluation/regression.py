from __future__ import annotations
from math import sqrt
from typing import Any


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    if trials <= 0:
        return 0.0, 0.0
    p = successes / trials
    denom = 1.0 + z * z / trials
    center = (p + z * z / (2 * trials)) / denom
    half = z * sqrt((p * (1 - p) + z * z / (4 * trials)) / trials) / denom
    return max(0.0, center - half), min(1.0, center + half)


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any], *, max_regression: float = 0.03, max_safety_increase: int = 0) -> dict[str, Any]:
    from .lab import EvaluationLab
    return EvaluationLab().compare(baseline, candidate, max_regression=max_regression, max_safety_increase=max_safety_increase)

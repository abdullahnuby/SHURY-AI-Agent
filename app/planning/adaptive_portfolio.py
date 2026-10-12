"""Deterministic adaptive algorithm portfolio.

The portfolio separates *data evidence* from *experience*. Evidence remains
primary; historical utility is a small, uncertainty-aware tie-breaker. This
prevents learned history from overriding a visibly better method on new data.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from statistics import mean

from app.knowledge.statistics.statistics_v13 import normalized_error, rolling_origin_mae
from app.knowledge.statistics.statistics_v12 import theil_sen


@dataclass(frozen=True)
class AlgorithmChoice:
    task: str
    method: str
    reason: str
    evidence_score: float
    learned_score: float
    final_score: float
    candidates: tuple[dict, ...]
    context: str


def context_signature(*, n: int, outlier_rate: float = 0.0, missing_rate: float = 0.0,
                      numeric_count: int = 0, categorical_count: int = 0, acf1: float | None = None) -> str:
    def bucket(x: float, cuts: tuple[float, ...]) -> str:
        for i, cut in enumerate(cuts):
            if x < cut:
                return str(i)
        return str(len(cuts))
    ac = 0.0 if acf1 is None else abs(acf1)
    return "|".join([
        f"n={bucket(float(n), (8, 20, 100, 1000))}",
        f"out={bucket(float(outlier_rate), (0.01, 0.05, 0.10, 0.25))}",
        f"miss={bucket(float(missing_rate), (0.01, 0.10, 0.25, 0.50))}",
        f"num={min(int(numeric_count), 5)}",
        f"cat={min(int(categorical_count), 5)}",
        f"acf={bucket(ac, (0.05, 0.20, 0.40, 0.70))}",
    ])


def _rows_for_method(memory, context: str, method: str) -> list[dict]:
    if memory is None:
        return []
    try:
        return memory.algorithm_observations(context, method)
    except Exception:
        return []


def learned_ucb(memory, context: str, method: str, exploration: float = 0.35) -> dict:
    """Recency-weighted empirical-Bernstein-like utility bound.

    Observations are weighted by recency in insertion order, so nonstationary
    workloads gradually forget stale evidence without random sampling.
    """
    rows = _rows_for_method(memory, context, method)
    if not rows:
        return {"mean": 0.5, "variance": 0.25, "count": 0, "ucb": 0.85, "method": method}
    # Most recent observation gets weight 1.0; each older row loses 15% weight.
    weights = [0.85 ** i for i in range(len(rows) - 1, -1, -1)]
    vals = [max(0.0, min(1.0, float(r["reward"]))) for r in rows]
    total = sum(weights)
    m = sum(w * v for w, v in zip(weights, vals)) / total
    var = sum(w * (v - m) ** 2 for w, v in zip(weights, vals)) / total
    n_eff = total * total / max(1e-12, sum(w * w for w in weights))
    bonus = exploration * math.sqrt(max(0.0, math.log(n_eff + 1.0) / max(1.0, n_eff)))
    bonus += 0.5 * exploration * math.sqrt(max(0.0, var))
    return {"mean": m, "variance": var, "count": len(rows), "effective_n": n_eff,
            "ucb": min(1.0, m + bonus), "method": method}


def select_trend_method(values: list[float], outlier_rate: float = 0.0, memory=None,
                        numeric_count: int = 1, categorical_count: int = 0) -> AlgorithmChoice:
    """Choose OLS/Theil-Sen from rolling-origin evidence, with learned prior as tie-breaker."""
    xs = [float(v) for v in values]
    from app.knowledge.statistics.statistics_v13 import autocorrelation
    acf1 = autocorrelation(xs, 1)
    context = context_signature(n=len(xs), outlier_rate=outlier_rate,
                                numeric_count=numeric_count, categorical_count=categorical_count, acf1=acf1)
    raw = {}
    for method in ("ols", "theil_sen"):
        mae = rolling_origin_mae(xs, method)
        ne = normalized_error(mae, xs)
        evidence = 1.0 / (1.0 + ne) if ne is not None else 0.0
        learned = learned_ucb(memory, context, method)
        # Evidence dominates. Learning contributes only up to 15% of the final score.
        final = 0.85 * evidence + 0.15 * learned["ucb"]
        raw[method] = {"method": method, "rolling_origin_mae": mae,
                       "normalized_mae": ne, "evidence_score": evidence,
                       "learned_ucb": learned["ucb"], "learned_count": learned["count"],
                       "final_score": final}
    order = {"ols": 0, "theil_sen": 1}
    winner = min((m for m in raw), key=lambda m: (-raw[m]["final_score"], order[m]))
    reason = "rolling-origin error favours robust trend" if winner == "theil_sen" else "rolling-origin error favours OLS"
    if outlier_rate >= 0.10 and winner == "theil_sen":
        reason += "; outlier rate supports robustness"
    candidates = tuple(raw[m] for m in sorted(raw))
    return AlgorithmChoice("trend", winner, reason, raw[winner]["evidence_score"],
                           raw[winner]["learned_ucb"], raw[winner]["final_score"], candidates, context)


def record_choice_outcome(memory, choice: AlgorithmChoice, verified: bool,
                          stability: float | None = None, efficiency: float | None = None) -> dict:
    """Record operational utility, not statistical correctness.

    Reward components are explicit: independent verification, stability, and
    runtime efficiency. Statistical correctness is not inferred from this score.
    """
    reward = 0.6 if verified else 0.0
    if stability is not None:
        reward += 0.25 * max(0.0, min(1.0, stability))
    if efficiency is not None:
        reward += 0.15 * max(0.0, min(1.0, efficiency))
    reward = max(0.0, min(1.0, reward))
    memory.record_algorithm_observation(choice.context, choice.method, reward,
                                        verified=verified,
                                        metadata={"task": choice.task, "reason": choice.reason})
    return {"context": choice.context, "method": choice.method, "reward": reward,
            "verified": bool(verified), "note": "operational utility; not ground-truth accuracy"}

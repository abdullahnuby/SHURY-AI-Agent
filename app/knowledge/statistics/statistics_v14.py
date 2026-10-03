"""V14 deterministic multivariate drift statistics.

Inspired by the September 2026 direction of adaptive online change detection:
use distributional distance in a low-dimensional projection space, then combine
it with an online scalar detector.  Everything here is standard-library only.
"""
from __future__ import annotations

import hashlib
import math
from statistics import mean, median
from app.knowledge.statistics.statistics_v12 import DeterministicRNG, _seed_from_text, percentile
from app.knowledge.statistics.statistics_v13 import autocorrelation


def _clean_matrix(rows: list[list[float]]) -> list[list[float]]:
    if not rows:
        return []
    d = len(rows[0])
    return [list(map(float, r)) for r in rows if len(r) == d and all(math.isfinite(float(x)) for x in r)]


def _quantile_sorted(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def wasserstein_1d(left: list[float], right: list[float], points: int = 101) -> float | None:
    """Empirical 1-Wasserstein distance via aligned quantiles."""
    a = sorted(float(x) for x in left if math.isfinite(float(x)))
    b = sorted(float(x) for x in right if math.isfinite(float(x)))
    if not a or not b:
        return None
    k = max(11, int(points))
    return mean(abs(_quantile_sorted(a, i / (k - 1)) - _quantile_sorted(b, i / (k - 1))) for i in range(k))


def _standardize_fit(base: list[list[float]], current: list[list[float]]) -> tuple[list[list[float]], list[list[float]], list[float], list[float]]:
    a = _clean_matrix(base); b = _clean_matrix(current)
    if not a or not b:
        return [], [], [], []
    d = len(a[0])
    means = [mean(r[j] for r in a) for j in range(d)]
    scales = []
    for j in range(d):
        q = [r[j] for r in a]
        m = means[j]
        sd = math.sqrt(mean((x - m) ** 2 for x in q)) if len(q) > 1 else 0.0
        scales.append(sd if sd > 1e-12 else 1.0)
    norm_a = [[(r[j] - means[j]) / scales[j] for j in range(d)] for r in a]
    norm_b = [[(r[j] - means[j]) / scales[j] for j in range(d)] for r in b]
    return norm_a, norm_b, means, scales


def _projection(d: int, seed_text: str, projection_index: int) -> list[float]:
    # Hash-derived Gaussian directions avoid correlated/repeating projections
    # from the tiny V12 PRNG when the modulo base is small.
    values = []
    for j in range(d):
        digest = hashlib.sha256(f"{seed_text}:{projection_index}:{j}".encode("utf-8")).digest()
        u1 = (int.from_bytes(digest[:8], "big") + 1) / (2**64 + 1)
        u2 = (int.from_bytes(digest[8:16], "big") + 1) / (2**64 + 1)
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        values.append(z)
    norm = math.sqrt(sum(x * x for x in values)) or 1.0
    return [x / norm for x in values]


def sliced_wasserstein_distance(
    base: list[list[float]], current: list[list[float]],
    projections: int = 16, seed_text: str = "", normalize: bool = True,
) -> dict:
    """Approximate multivariate distribution shift using deterministic projections."""
    if normalize:
        a, b, means, scales = _standardize_fit(base, current)
    else:
        a, b = _clean_matrix(base), _clean_matrix(current)
        means, scales = [], []
    if not a or not b or len(a[0]) == 0:
        return {"distance": None, "projections": 0, "dimension": 0, "method": "sliced_wasserstein"}
    d = len(a[0])
    seed = seed_text or repr(a[:16]) + repr(b[:16])
    distances = []
    for projection_index in range(max(4, int(projections))):
        direction = _projection(d, seed, projection_index)
        pa = [sum(row[j] * direction[j] for j in range(d)) for row in a]
        pb = [sum(row[j] * direction[j] for j in range(d)) for row in b]
        w = wasserstein_1d(pa, pb)
        if w is not None:
            distances.append(w)
    return {
        "distance": mean(distances) if distances else None,
        "distance_std": math.sqrt(mean((x - mean(distances)) ** 2 for x in distances)) if len(distances) > 1 else 0.0,
        "projections": len(distances), "dimension": d,
        "method": "deterministic_rademacher_sliced_wasserstein",
        "standardized": normalize,
        "baseline_means": means,
        "baseline_scales": scales,
    }


def multivariate_drift(base: list[list[float]], current: list[list[float]],
                        column_names: list[str], threshold: float = 0.25,
                        seed_text: str = "") -> dict:
    """Return global + per-column distribution shift evidence."""
    if not base or not current:
        return {"alert": False, "reason": "insufficient_data", "columns": {}}
    global_drift = sliced_wasserstein_distance(base, current, seed_text=seed_text)
    a, b, _, scales = _standardize_fit(base, current)
    cols = {}
    for j, name in enumerate(column_names[:len(a[0])]):
        wa = [r[j] for r in a]; wb = [r[j] for r in b]
        dist = wasserstein_1d(wa, wb)
        cols[name] = {
            "standardized_wasserstein": dist,
            "alert": bool(dist is not None and dist >= threshold),
            "baseline_scale": scales[j],
        }
    global_distance = global_drift.get("distance")
    return {
        "method": "multivariate_distribution_drift",
        "global": global_drift,
        "global_alert": bool(global_distance is not None and global_distance >= threshold),
        "threshold": threshold,
        "columns": cols,
        "alert": bool(global_distance is not None and global_distance >= threshold) or any(v["alert"] for v in cols.values()),
    }


def robust_recent_window(values: list[float], window: int = 20) -> tuple[list[float], list[float]]:
    xs = [float(x) for x in values if math.isfinite(float(x))]
    if len(xs) <= window:
        cut = max(2, len(xs) // 2)
    else:
        cut = window
    return xs[:-cut] or xs, xs[-cut:]


def adaptive_distribution_signal(values: list[float], window: int = 20,
                                 threshold: float = 0.35) -> dict:
    """Self-calibrating univariate drift from recent-vs-reference distributions."""
    base, recent = robust_recent_window(values, window)
    if len(base) < 5 or len(recent) < 3:
        return {"alert": False, "method": "adaptive_wasserstein_recent_window", "distance": None}
    med = median(base)
    scale = median([abs(x - med) for x in base]) * 1.4826
    scale = max(scale, 1e-9)
    distance = (wasserstein_1d([(x - med) / scale for x in base], [(x - med) / scale for x in recent]) or 0.0)
    return {
        "method": "adaptive_wasserstein_recent_window",
        "distance": distance,
        "threshold": threshold,
        "alert": distance >= threshold,
        "reference_n": len(base), "recent_n": len(recent),
        "reference_median": med, "reference_robust_scale": scale,
        "autocorrelation_lag1": autocorrelation(values, 1),
    }

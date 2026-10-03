"""Model-free statistical algorithms for V12.

Standard-library only.  Deterministic bootstrap uses a seed derived from the
input fingerprint so the same data yields the same interval and evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from collections import Counter
from statistics import mean, median
from typing import Iterable


def _seed_from_text(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


class DeterministicRNG:
    """Tiny deterministic PRNG; reproducible across processes/Python builds."""
    def __init__(self, seed: int):
        self.state = seed & ((1 << 64) - 1)

    def next_u64(self) -> int:
        self.state = (6364136223846793005 * self.state + 1442695040888963407) & ((1 << 64) - 1)
        return self.state

    def randbelow(self, n: int) -> int:
        if n <= 0:
            raise ValueError("n must be positive")
        return self.next_u64() % n


def percentile(values: Iterable[float], q: float) -> float | None:
    xs = sorted(float(v) for v in values)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    q = max(0.0, min(1.0, q))
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def bootstrap_ci(values: list[float], statistic: str = "mean", confidence: float = 0.95,
                 iterations: int = 1000, seed_text: str = "") -> dict:
    xs = [float(v) for v in values]
    if len(xs) < 2:
        return {"estimate": mean(xs) if xs else None, "lower": None, "upper": None,
                "confidence": confidence, "iterations": 0, "method": "insufficient_sample"}
    fn = mean if statistic == "mean" else median
    rng = DeterministicRNG(_seed_from_text(seed_text or repr(xs)))
    estimates: list[float] = []
    n = len(xs)
    for _ in range(max(50, int(iterations))):
        sample = [xs[rng.randbelow(n)] for _ in range(n)]
        estimates.append(fn(sample))
    alpha = 1.0 - max(0.0, min(0.999, confidence))
    return {
        "estimate": fn(xs),
        "lower": percentile(estimates, alpha / 2),
        "upper": percentile(estimates, 1 - alpha / 2),
        "confidence": confidence,
        "iterations": len(estimates),
        "method": "deterministic_percentile_bootstrap",
    }


def theil_sen(values: list[float]) -> dict:
    """Robust slope/intercept over ordered observations."""
    n = len(values)
    if n < 2:
        return {"slope": None, "intercept": None, "n": n}
    slopes = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            slopes.append((values[j] - values[i]) / (j - i))
    slope = median(slopes)
    intercept = median([y - slope * x for x, y in enumerate(values)])
    preds = [slope * i + intercept for i in range(n)]
    my = mean(values)
    ss_tot = sum((y - my) ** 2 for y in values)
    ss_res = sum((y - p) ** 2 for y, p in zip(values, preds))
    r2 = 1.0 if ss_tot == 0 else max(0.0, 1.0 - ss_res / ss_tot)
    return {"slope": slope, "intercept": intercept, "r2": r2, "n": n, "method": "theil_sen"}


def robust_z_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    med = median(values)
    mad = median([abs(x - med) for x in values])
    if mad == 0:
        return [0.0 if x == med else math.inf * (1 if x > med else -1) for x in values]
    scale = 1.4826 * mad
    return [(x - med) / scale for x in values]


def mutual_information(xs: list[str], ys: list[str]) -> float | None:
    if len(xs) != len(ys) or not xs:
        return None
    n = len(xs)
    joint = Counter(zip(xs, ys)); cx = Counter(xs); cy = Counter(ys)
    mi = 0.0
    for (x, y), count in joint.items():
        pxy = count / n; px = cx[x] / n; py = cy[y] / n
        mi += pxy * math.log(pxy / (px * py), 2)
    return mi


def discretize_numeric(values: list[float], bins: int = 5) -> list[str]:
    if not values:
        return []
    if len(set(values)) <= 1:
        return ["0"] * len(values)
    cuts = [percentile(values, i / bins) for i in range(1, bins)]
    out = []
    for v in values:
        idx = 0
        for cut in cuts:
            if cut is not None and v >= cut:
                idx += 1
        out.append(str(idx))
    return out


def categorical_entropy(values: list[str]) -> float | None:
    if not values:
        return None
    counts = Counter(values)
    n = len(values)
    return -sum((c / n) * math.log(c / n, 2) for c in counts.values())


def js_divergence(base: list[str], current: list[str]) -> float | None:
    if not base or not current:
        return None
    b, c = Counter(base), Counter(current)
    keys = sorted(set(b) | set(c))
    nb, nc = len(base), len(current)
    js = 0.0
    for k in keys:
        p = b.get(k, 0) / nb
        q = c.get(k, 0) / nc
        m = (p + q) / 2
        if p > 0:
            js += 0.5 * p * math.log(p / m, 2)
        if q > 0:
            js += 0.5 * q * math.log(q / m, 2)
    return js


def cliffs_delta(a: list[float], b: list[float]) -> float | None:
    if not a or not b:
        return None
    greater = less = 0
    for x in a:
        for y in b:
            if x > y:
                greater += 1
            elif x < y:
                less += 1
    return (greater - less) / (len(a) * len(b))


def page_hinkley(values: list[float], delta: float = 0.005, threshold: float = 5.0) -> dict:
    """One-pass change detector useful for online monitoring."""
    if len(values) < 5:
        return {"change": False, "index": None, "statistic": 0.0, "method": "page_hinkley"}
    mean_est = values[0]
    cumulative = 0.0
    minimum = 0.0
    max_stat = 0.0
    change_index = None
    for i, x in enumerate(values[1:], start=1):
        mean_est += (x - mean_est) / (i + 1)
        cumulative += x - mean_est - delta
        minimum = min(minimum, cumulative)
        stat = cumulative - minimum
        if stat > max_stat:
            max_stat = stat
        if change_index is None and stat > threshold:
            change_index = i
    return {"change": change_index is not None, "index": change_index,
            "statistic": max_stat, "method": "page_hinkley"}


@dataclass(frozen=True)
class AnalysisMethodChoice:
    method: str
    reason: str


def choose_trend_method(values: list[float], outlier_rate: float = 0.0) -> AnalysisMethodChoice:
    if len(values) >= 8 and outlier_rate >= 0.10:
        return AnalysisMethodChoice("theil_sen", "حجم عينة كافٍ مع شذوذ ملحوظ؛ استخدمت اتجاهًا robust")
    return AnalysisMethodChoice("ols", "OLS مناسب للاتجاه الأساسي مع حساسية مقبولة للشذوذ الحالي")

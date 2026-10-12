"""V13 statistical methods for dependence-aware uncertainty and online selection.

Standard-library only. The methods are deterministic and intended for small-to-
medium local datasets where auditability matters more than raw throughput.
"""
from __future__ import annotations

import math
from statistics import mean, median
from app.knowledge.statistics.statistics_v12 import DeterministicRNG, _seed_from_text, percentile


def autocorrelation(values: list[float], lag: int = 1) -> float | None:
    xs = [float(v) for v in values]
    if lag < 1 or len(xs) <= lag + 1:
        return None
    a, b = xs[:-lag], xs[lag:]
    ma, mb = mean(a), mean(b)
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0.0 or db == 0.0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (da * db)


def _block_length(values: list[float]) -> int:
    n = len(values)
    acf = autocorrelation(values, 1)
    if n < 12 or acf is None:
        return 1
    # A deterministic dependence-aware default. Stronger dependence => longer blocks.
    strength = abs(acf)
    if strength < 0.20:
        return 1
    length = int(round(n ** (1.0 / 3.0) * (1.0 + 2.0 * strength)))
    return max(2, min(length, max(2, n // 3)))


def moving_block_bootstrap_ci(
    values: list[float],
    statistic: str = "mean",
    confidence: float = 0.95,
    iterations: int = 800,
    seed_text: str = "",
    block_length: int | None = None,
) -> dict:
    """Percentile moving-block bootstrap for ordered/dependent observations."""
    xs = [float(v) for v in values]
    if len(xs) < 4:
        return {"estimate": mean(xs) if xs else None, "lower": None, "upper": None,
                "confidence": confidence, "iterations": 0, "block_length": None,
                "method": "insufficient_sample"}
    fn = mean if statistic == "mean" else median
    block = max(2, int(block_length or _block_length(xs)))
    if block >= len(xs):
        block = max(2, len(xs) // 2)
    starts = max(1, len(xs) - block + 1)
    rng = DeterministicRNG(_seed_from_text(seed_text or repr(xs)))
    estimates: list[float] = []
    n = len(xs)
    for _ in range(max(50, int(iterations))):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.randbelow(starts)
            sample.extend(xs[start:start + block])
        estimates.append(fn(sample[:n]))
    alpha = 1.0 - max(0.0, min(0.999, confidence))
    return {
        "estimate": fn(xs),
        "lower": percentile(estimates, alpha / 2),
        "upper": percentile(estimates, 1 - alpha / 2),
        "confidence": confidence,
        "iterations": len(estimates),
        "block_length": block,
        "autocorrelation_lag1": autocorrelation(xs, 1),
        "method": "deterministic_moving_block_bootstrap",
    }


def choose_confidence_interval_method(values: list[float], dependency_threshold: float = 0.20) -> dict:
    """Select IID vs moving-block bootstrap using measured serial dependence."""
    acf = autocorrelation(values, 1)
    use_block = acf is not None and abs(acf) >= dependency_threshold and len(values) >= 12
    return {
        "method": "moving_block_bootstrap" if use_block else "iid_bootstrap",
        "reason": "serial dependence detected" if use_block else "insufficient/weak serial dependence",
        "autocorrelation_lag1": acf,
        "threshold": dependency_threshold,
    }


def rolling_origin_mae(values: list[float], method: str, min_train: int = 5) -> float | None:
    """One-step-ahead error for the trend estimator without external dependencies."""
    xs = [float(v) for v in values]
    if len(xs) <= min_train:
        return None
    from app.knowledge.statistics.statistics_v12 import theil_sen
    from app.knowledge.data_analysis import _linear_trend
    errors = []
    for i in range(min_train, len(xs)):
        train = xs[:i]
        if method == "theil_sen":
            fit = theil_sen(train)
            slope, intercept = fit["slope"], fit["intercept"]
            pred = intercept + slope * i
        else:
            slope, r2 = _linear_trend(train)
            if slope is None:
                continue
            intercept = mean(train) - slope * ((i - 1) / 2.0)
            pred = intercept + slope * i
        errors.append(abs(xs[i] - pred))
    return mean(errors) if errors else None


def normalized_error(error: float | None, values: list[float]) -> float | None:
    if error is None or not values:
        return None
    med = median(values)
    mad = median([abs(x - med) for x in values])
    scale = max(1e-12, 1.4826 * mad)
    if scale == 1e-12:
        spread = max(values) - min(values)
        scale = max(1e-12, spread)
    return error / scale

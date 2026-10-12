"""Deterministic memory consolidation and forgetting policies."""
from __future__ import annotations

from collections import Counter
import math
import time


def score_stability(*, confirmations: int, confidence: float, importance: int, access_count: int) -> float:
    confirmation = 1.0 - math.exp(-max(0, confirmations) / 2.0)
    return round(0.40 * confirmation + 0.30 * confidence + 0.20 * (importance / 5.0) + 0.10 * min(access_count, 10) / 10.0, 4)


def stale(*, updated_at: str | None, half_life_days: float = 180.0) -> bool:
    if not updated_at:
        return False
    try:
        then = time.mktime(time.strptime(updated_at, "%Y-%m-%dT%H:%M:%S"))
        return (time.time() - then) > half_life_days * 86400
    except Exception:
        return False

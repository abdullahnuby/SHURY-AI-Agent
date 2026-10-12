from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after: float = 0.0


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class RateLimiter:
    """Process-local token bucket. Durable writes remain in the DB; throttling is a fast edge guard."""

    def __init__(self, capacity: int = 60, refill_per_second: float = 1.0, clock=None):
        self.capacity = float(max(1, capacity))
        self.refill_per_second = max(0.01, float(refill_per_second))
        self.clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str, cost: float = 1.0) -> RateLimitDecision:
        now = self.clock()
        spend = max(0.1, float(cost))
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(self.capacity, now)
                self._buckets[key] = bucket
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_per_second)
                bucket.updated_at = now
            if bucket.tokens >= spend:
                bucket.tokens -= spend
                return RateLimitDecision(True, max(0, int(bucket.tokens)), 0.0)
            deficit = spend - bucket.tokens
            retry = deficit / self.refill_per_second
            return RateLimitDecision(False, max(0, int(bucket.tokens)), max(0.05, retry))

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


__all__ = ["RateLimiter", "RateLimitDecision"]

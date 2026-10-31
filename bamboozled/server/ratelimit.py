"""Token buckets driven by an injectable clock, so tests never sleep."""
from __future__ import annotations

from typing import Callable


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: int, clock_ms: Callable[[], int]):
        self.rate, self.burst, self.clock = rate_per_s, burst, clock_ms
        self.tokens = float(burst)
        self.stamp = clock_ms()

    def allow(self, cost: float = 1.0) -> bool:
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.stamp) * self.rate / 1000)
        self.stamp = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class KeyedLimiter:
    """A bucket per key (an IP, an OAuth code). Old keys are dropped so memory stays bounded."""

    def __init__(self, rate_per_s: float, burst: int, clock_ms: Callable[[], int], max_keys: int = 10_000):
        self.rate, self.burst, self.clock, self.max_keys = rate_per_s, burst, clock_ms, max_keys
        self.buckets: dict[str, TokenBucket] = {}

    def allow(self, key: str) -> bool:
        b = self.buckets.get(key)
        if b is None:
            if len(self.buckets) >= self.max_keys:
                self.buckets.pop(next(iter(self.buckets)))
            b = self.buckets[key] = TokenBucket(self.rate, self.burst, self.clock)
        return b.allow()

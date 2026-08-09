"""Small thread-safe token bucket for provider adapters."""
from __future__ import annotations

import threading
import time


class TokenBucket:
    def __init__(self, rate_per_second: float, capacity: int):
        if rate_per_second <= 0 or capacity < 1:
            raise ValueError("rate and capacity must be positive")
        self.rate, self.capacity = float(rate_per_second), int(capacity)
        self.tokens, self.updated = float(capacity), time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, amount: float = 1.0) -> float:
        """Return required wait seconds; callers choose sync/async sleeping."""
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= amount:
                self.tokens -= amount
                return 0.0
            return (amount - self.tokens) / self.rate

"""In-process sliding-window rate limiter.

Good for a single API process. With several replicas each keeps its own
window, so the effective limit multiplies; move this to Redis before scaling
out (the interface stays the same).
"""

import math
import threading
import time
from collections import deque

from app.errors import TooManyRequests


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, max_keys: int = 50_000):
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, *, now: float | None = None) -> None:
        """Record one attempt; raise TooManyRequests if the key is over its limit."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self.max_keys:
                    self._evict(now)
                hits = self._hits[key] = deque()
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = max(1, math.ceil(hits[0] + self.window - now))
                raise TooManyRequests("Too many requests. Try again shortly.", retry_after=retry_after)
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _evict(self, now: float) -> None:
        stale = [k for k, h in self._hits.items() if not h or h[-1] <= now - self.window]
        for key in stale:
            del self._hits[key]
        if len(self._hits) >= self.max_keys:  # still full: drop the oldest half
            for key in list(self._hits)[: self.max_keys // 2]:
                del self._hits[key]

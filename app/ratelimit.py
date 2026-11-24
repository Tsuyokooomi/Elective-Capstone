"""A small in-memory rate limiter (sliding window).

Counts requests per key (a user, or an IP address) inside a time window. The counters live in the
API process: they reset on restart and are not shared between several API processes. That is fine
for this project. A deployment with several workers would use Redis."""
import threading
import time
from collections import deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict[str, tuple[int, deque]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: int) -> int:
        """Record one request. Returns 0 if it is allowed, else the seconds to wait."""
        now = self._clock()
        with self._lock:
            _, hits = self._hits.setdefault(key, (window, deque()))
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, int(window - (now - hits[0])) + 1)
            hits.append(now)
            if len(self._hits) > 10_000:
                self._prune(now)
            return 0

    def _prune(self, now: float) -> None:
        for key in [k for k, (window, hits) in self._hits.items() if not hits or now - hits[-1] >= window]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def enforce(key: str, limit: int, window: int, message: str) -> None:
    """Raise 429 if the key has used up its allowance. {seconds} in the message is the wait time."""
    wait = limiter.check(key, limit, window)
    if wait:
        raise HTTPException(status_code=429, detail=message.format(seconds=wait), headers={"Retry-After": str(wait)})

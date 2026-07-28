"""A token bucket shared by every caller of the YGOPRODeck API.

Their guide states 20 requests per second, and exceeding it blocks the IP for an
hour. One process-wide bucket well under that ceiling is the only thing standing
between a bulk job and a day of downtime, so providers, the image cache and the
per-printing refinement job all draw from this same budget rather than each
keeping their own.
"""

from __future__ import annotations

import asyncio
import time

from ..config import REQUESTS_PER_SECOND

__all__ = ["TokenBucket", "shared_limiter"]


class TokenBucket:
    """Async token bucket. ``acquire`` waits until a token is available."""

    def __init__(self, rate_per_second: float, burst: int | None = None) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self.rate = rate_per_second
        self.capacity = float(burst if burst is not None else max(1, int(rate_per_second)))
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self._tokens) / self.rate)


_shared: TokenBucket | None = None


def shared_limiter() -> TokenBucket:
    """The one bucket. Created lazily so importing this module costs nothing."""
    global _shared
    if _shared is None:
        _shared = TokenBucket(REQUESTS_PER_SECOND)
    return _shared

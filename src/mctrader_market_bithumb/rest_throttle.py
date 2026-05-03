"""RestThrottle — async self-throttle for Bithumb Public REST (MCT-33, ADR-007 D4).

ADR-007 D4 specifies Public REST 5/sec hard limit. This adapter-side self-throttle
keeps the consumer-side at 5/sec without needing engine-level coordination — REST
calls go through this gate before they hit Bithumb.

Sliding window (deque[float] of monotonic timestamps). awaits asyncio.sleep when
the window is full so callers can simply ``await throttle.acquire()`` before each
request.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque


class RestThrottle:
    """Async sliding-window throttle for Bithumb Public REST."""

    def __init__(self, *, limit_per_sec: int = 5) -> None:
        if limit_per_sec <= 0:
            raise ValueError("limit_per_sec must be positive")
        self._limit = limit_per_sec
        self._window_seconds = 1.0
        self._events: deque[float] = deque()
        self._lock = asyncio.Lock()

    @property
    def limit_per_sec(self) -> int:
        return self._limit

    def _evict(self, *, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    async def acquire(self) -> None:
        """Block until a request slot is free; record the request timestamp on exit."""
        async with self._lock:
            while True:
                now = time.monotonic()
                self._evict(now=now)
                if len(self._events) < self._limit:
                    self._events.append(now)
                    return
                # Sleep until the oldest event leaves the window.
                wait_seconds = (self._events[0] + self._window_seconds) - now
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

    def in_flight_count(self) -> int:
        """Inspector: count of timestamps currently within window (sync, monotonic-now)."""
        now = time.monotonic()
        self._evict(now=now)
        return len(self._events)

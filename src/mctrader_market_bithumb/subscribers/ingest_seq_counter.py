"""Per-process monotonic ingest_seq counter (MCT-138, Epic MCT-112 Story-4).

Contract:
- Starts at 0 on instantiation.
- ``next()`` returns the current value and advances by 1 (uint64 semantics).
- ``reset()`` returns the counter to 0.
- Thread-safe / coroutine-safe (asyncio.Lock-free using :class:`itertools.count`
  + threading.Lock around the count generator for the reset operation).

Restart semantics (per Story-6 WAL dedup policy): a fresh process instantiates
a fresh counter — there is no on-disk persistence. Dedup must be performed
downstream by ``(exchange, symbol, ts_utc, trade_id, payload_hash)``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from itertools import count


class IngestSeqCounter:
    """Monotonic uint64-style counter for per-process tick ingest sequencing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gen: Iterator[int] = count(0)

    def next(self) -> int:
        """Return the current sequence value and advance by 1."""
        with self._lock:
            return next(self._gen)

    def reset(self) -> None:
        """Reset the counter to 0 (next ``next()`` returns 0)."""
        with self._lock:
            self._gen = count(0)

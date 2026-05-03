"""RestThrottle tests (MCT-33, ADR-007 D4 Public REST 5/sec).

Uses asyncio.run() directly (no pytest-asyncio dependency).
"""

from __future__ import annotations

import asyncio
import time

import pytest

from mctrader_market_bithumb.rest_throttle import RestThrottle


def test_invalid_limit_raises() -> None:
    with pytest.raises(ValueError):
        RestThrottle(limit_per_sec=0)
    with pytest.raises(ValueError):
        RestThrottle(limit_per_sec=-1)


def test_default_limit_is_five() -> None:
    throttle = RestThrottle()
    assert throttle.limit_per_sec == 5


def test_under_limit_acquires_immediately() -> None:
    async def runner() -> float:
        throttle = RestThrottle(limit_per_sec=5)
        start = time.monotonic()
        for _ in range(5):
            await throttle.acquire()
        return time.monotonic() - start

    elapsed = asyncio.run(runner())
    # 5 acquires within 5/sec limit should be near-instant.
    assert elapsed < 0.5, f"under-limit acquires should be fast, got {elapsed}s"


def test_exceeds_limit_waits_for_window_to_pass() -> None:
    async def runner() -> float:
        throttle = RestThrottle(limit_per_sec=2)
        start = time.monotonic()
        # Issue 3 requests; 3rd must wait ~1s.
        for _ in range(3):
            await throttle.acquire()
        return time.monotonic() - start

    elapsed = asyncio.run(runner())
    assert elapsed >= 0.9, f"3rd acquire under 2/sec should wait ~1s, got {elapsed}s"


def test_window_eviction_releases_slots() -> None:
    async def runner() -> float:
        throttle = RestThrottle(limit_per_sec=2)
        await throttle.acquire()
        await throttle.acquire()
        # Wait > 1s for events to age out of the sliding window.
        await asyncio.sleep(1.05)
        start = time.monotonic()
        await throttle.acquire()
        return time.monotonic() - start

    elapsed = asyncio.run(runner())
    assert elapsed < 0.1, f"after window eviction acquire should be fast, got {elapsed}s"


def test_concurrent_acquires_are_serialized() -> None:
    async def runner() -> list[float]:
        throttle = RestThrottle(limit_per_sec=2)

        async def worker() -> float:
            t0 = time.monotonic()
            await throttle.acquire()
            return time.monotonic() - t0

        return await asyncio.gather(*(worker() for _ in range(4)))

    results = asyncio.run(runner())
    fast = [r for r in results if r < 0.3]
    slow = [r for r in results if r >= 0.5]
    assert len(fast) == 2, f"expected 2 fast acquires, got {fast}"
    assert len(slow) == 2, f"expected 2 slow acquires (~1s), got {slow}"


def test_in_flight_count_initial_zero() -> None:
    throttle = RestThrottle()
    assert throttle.in_flight_count() == 0


def test_in_flight_count_after_acquires() -> None:
    async def runner() -> int:
        throttle = RestThrottle(limit_per_sec=5)
        for _ in range(3):
            await throttle.acquire()
        return throttle.in_flight_count()

    assert asyncio.run(runner()) == 3

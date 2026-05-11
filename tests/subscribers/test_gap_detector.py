"""GapDetector tests — sequence hole / large ts jump / reconnect_boundary (MCT-138).

ADR-009 §D12.2 — Bithumb public API does not provide ticks historical replay.
Gap detection produces *evidence* (GapEvent / validation_status = GAP), it does
not attempt backfill — downstream consumers (Story-6 WAL) treat the affected
window as unrecoverable for strategy input.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from mctrader_market.types import Symbol

from mctrader_market_bithumb.subscribers import (
    GAP_THRESHOLD_SECONDS_DEFAULT,
    GapDetector,
    GapEvent,
)

SYM = Symbol(base="BTC", quote="KRW")
T0 = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _ts(seconds_offset: float) -> datetime:
    return T0 + timedelta(seconds=seconds_offset)


# ── default threshold ─────────────────────────────────────────────────────


def test_default_threshold_is_one_second() -> None:
    assert GAP_THRESHOLD_SECONDS_DEFAULT == 1.0


# ── monotonic timestamps → no gap ─────────────────────────────────────────


def test_no_gap_on_first_event() -> None:
    detector = GapDetector()
    ev = detector.observe(symbol=SYM, event_time=_ts(0))
    assert ev is None


def test_no_gap_for_close_timestamps() -> None:
    detector = GapDetector(threshold_seconds=1.0)
    detector.observe(symbol=SYM, event_time=_ts(0))
    ev = detector.observe(symbol=SYM, event_time=_ts(0.5))
    assert ev is None


def test_no_gap_at_threshold_boundary() -> None:
    """Jump equal to threshold is NOT a gap (strict inequality)."""
    detector = GapDetector(threshold_seconds=1.0)
    detector.observe(symbol=SYM, event_time=_ts(0))
    ev = detector.observe(symbol=SYM, event_time=_ts(1.0))
    assert ev is None


# ── ts jump > threshold → GAP ─────────────────────────────────────────────


def test_large_ts_jump_emits_gap_event() -> None:
    detector = GapDetector(threshold_seconds=1.0)
    detector.observe(symbol=SYM, event_time=_ts(0))
    ev = detector.observe(symbol=SYM, event_time=_ts(5.0))
    assert isinstance(ev, GapEvent)
    assert ev.symbol == SYM
    assert ev.kind == "TS_JUMP"
    assert ev.gap_seconds == pytest.approx(5.0)
    assert ev.previous_ts == _ts(0)
    assert ev.current_ts == _ts(5.0)


def test_gap_event_emits_warning_log(caplog: pytest.LogCaptureFixture) -> None:
    detector = GapDetector(threshold_seconds=1.0)
    detector.observe(symbol=SYM, event_time=_ts(0))
    with caplog.at_level(logging.WARNING):
        detector.observe(symbol=SYM, event_time=_ts(3.0))
    assert any("GAP" in r.getMessage() for r in caplog.records)


def test_custom_threshold_seconds() -> None:
    detector = GapDetector(threshold_seconds=10.0)
    detector.observe(symbol=SYM, event_time=_ts(0))
    # 5s jump under 10s threshold → no gap
    assert detector.observe(symbol=SYM, event_time=_ts(5.0)) is None
    # 11s jump from 5.0 → gap
    ev = detector.observe(symbol=SYM, event_time=_ts(16.0))
    assert isinstance(ev, GapEvent)


# ── reconnect_boundary ────────────────────────────────────────────────────


def test_mark_reconnect_returns_reconnect_event() -> None:
    detector = GapDetector()
    ev = detector.mark_reconnect(at=_ts(0))
    assert isinstance(ev, GapEvent)
    assert ev.kind == "RECONNECT_BOUNDARY"
    assert ev.current_ts == _ts(0)


def test_first_event_after_reconnect_not_classified_as_gap() -> None:
    """Per-symbol state must reset after reconnect (matches ws_client._last_ts.clear())."""
    detector = GapDetector(threshold_seconds=1.0)
    detector.observe(symbol=SYM, event_time=_ts(0))
    detector.mark_reconnect(at=_ts(10))
    # Far jump after reconnect — must NOT be a gap (state was cleared).
    ev = detector.observe(symbol=SYM, event_time=_ts(100))
    assert ev is None


# ── per-symbol independence ───────────────────────────────────────────────


def test_per_symbol_state_isolated() -> None:
    detector = GapDetector(threshold_seconds=1.0)
    a = Symbol(base="BTC", quote="KRW")
    b = Symbol(base="ETH", quote="KRW")
    detector.observe(symbol=a, event_time=_ts(0))
    # First observation for symbol b — never a gap.
    assert detector.observe(symbol=b, event_time=_ts(100)) is None
    # symbol a still tracked separately; large jump for a → gap.
    assert isinstance(detector.observe(symbol=a, event_time=_ts(10)), GapEvent)


# ── out-of-order rejection ────────────────────────────────────────────────


def test_out_of_order_is_not_gap() -> None:
    """ws_client already drops out-of-order msgs (lines 122-136); detector mirrors that."""
    detector = GapDetector(threshold_seconds=1.0)
    detector.observe(symbol=SYM, event_time=_ts(10))
    # later event_time goes backward → out-of-order, not a gap event.
    ev = detector.observe(symbol=SYM, event_time=_ts(5))
    assert ev is None

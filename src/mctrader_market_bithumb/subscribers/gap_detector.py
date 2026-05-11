"""GapDetector — sequence hole / timestamp jump / WS reconnect boundary (MCT-138).

ADR-009 §D12.2: Bithumb public API does NOT provide ticks historical replay.
This detector produces *evidence* only — it does not attempt any backfill.
Downstream consumers (Story-6 WAL, Story-7 strategy gating) MUST exclude
GAP / RECONNECT_BOUNDARY windows from strategy input.

Design notes:
- Per-symbol state ``(symbol → last_event_time)``.
- Jump detection uses STRICT inequality: ``dt > threshold`` is a gap,
  ``dt == threshold`` is not (matches "more than N seconds" intent).
- Out-of-order events (event_time <= last) are NOT classified as gaps —
  :class:`BithumbWebSocketStream` already drops these earlier in the pipeline
  (ws_client.py lines 122-136). We mirror that behavior here for safety.
- ``mark_reconnect()`` clears all per-symbol state so the first message after
  reconnect is never spuriously classified as a gap (matches
  ws_client._last_ts.clear() on (re)connect).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from mctrader_market.types import Symbol

logger = logging.getLogger(__name__)

GAP_THRESHOLD_SECONDS_DEFAULT: float = 1.0
"""Default jump threshold (1 second) — Bithumb transaction cadence is sub-second
in liquid markets, so a >1s gap is anomalous (ADR-009 §D12.2)."""


GapKind = Literal["TS_JUMP", "RECONNECT_BOUNDARY"]


@dataclass(frozen=True)
class GapEvent:
    """Evidence record for a detected gap or reconnect boundary."""

    symbol: Symbol | None  # None for RECONNECT_BOUNDARY (process-level, no symbol)
    kind: GapKind
    previous_ts: datetime | None
    current_ts: datetime
    gap_seconds: float


class GapDetector:
    """Per-symbol gap detector with reconnect-boundary marker.

    Usage:
        detector = GapDetector()
        for event in stream.messages():
            gap = detector.observe(symbol=event.symbol, event_time=event.event_time)
            if gap is not None:
                # tag downstream row with validation_status=GAP
                ...

        # On WS reconnect:
        detector.mark_reconnect(at=now_utc)
    """

    def __init__(self, *, threshold_seconds: float = GAP_THRESHOLD_SECONDS_DEFAULT) -> None:
        self._threshold = threshold_seconds
        self._last: dict[tuple[str, str], datetime] = {}

    @property
    def threshold_seconds(self) -> float:
        return self._threshold

    def observe(self, *, symbol: Symbol, event_time: datetime) -> GapEvent | None:
        """Record an observation, returning a :class:`GapEvent` if a jump > threshold occurred."""
        key = (symbol.base, symbol.quote)
        prev = self._last.get(key)
        self._last[key] = event_time
        if prev is None:
            return None
        if event_time <= prev:
            # Out-of-order or duplicate — not a gap. Restore prev so we don't
            # poison state with a backwards timestamp.
            self._last[key] = prev
            return None
        dt = (event_time - prev).total_seconds()
        if dt > self._threshold:
            logger.warning(
                "GAP detected: symbol=%s/%s gap=%.3fs prev=%s curr=%s (ADR-009 §D12.2: no backfill)",
                symbol.base,
                symbol.quote,
                dt,
                prev.isoformat(),
                event_time.isoformat(),
            )
            return GapEvent(
                symbol=symbol,
                kind="TS_JUMP",
                previous_ts=prev,
                current_ts=event_time,
                gap_seconds=dt,
            )
        return None

    def mark_reconnect(self, *, at: datetime) -> GapEvent:
        """Mark a WS reconnect boundary — clears per-symbol state and returns a marker event."""
        self._last.clear()
        logger.warning(
            "RECONNECT_BOUNDARY at %s — per-symbol gap state cleared (ADR-009 §D12.2)",
            at.isoformat(),
        )
        return GapEvent(
            symbol=None,
            kind="RECONNECT_BOUNDARY",
            previous_ts=None,
            current_ts=at,
            gap_seconds=0.0,
        )

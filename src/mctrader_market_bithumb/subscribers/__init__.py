"""Bithumb realtime subscribers — tick.v1.1 emit + gap detection (MCT-138).

Public API:
- :class:`IngestSeqCounter` — monotonic per-process counter (collector start = 0).
- :class:`GapDetector` — sequence/timestamp gap classifier (ADR-009 §D12.2).
- :func:`build_transaction_tick_row` — Bithumb transaction WS frame → tick.v1.1.

ADR-009 §D12.2: Bithumb public API does *not* provide ticks historical replay
(no backfill). When :class:`GapDetector` reports ``GAP``, downstream
consumers (Story-6 WAL, Story-7 strategy gating) MUST treat the affected
window as unrecoverable and exclude it from strategy input.
"""

from __future__ import annotations

from mctrader_market_bithumb.subscribers.gap_detector import (
    GAP_THRESHOLD_SECONDS_DEFAULT,
    GapDetector,
    GapEvent,
)
from mctrader_market_bithumb.subscribers.ingest_seq_counter import IngestSeqCounter
from mctrader_market_bithumb.subscribers.transaction_ws import (
    MalformedPayloadError,
    QuarantineRecord,
    TransactionTickEmitter,
    build_transaction_tick_row,
    compute_payload_hash,
)

__all__ = [
    "GAP_THRESHOLD_SECONDS_DEFAULT",
    "GapDetector",
    "GapEvent",
    "IngestSeqCounter",
    "MalformedPayloadError",
    "QuarantineRecord",
    "TransactionTickEmitter",
    "build_transaction_tick_row",
    "compute_payload_hash",
]

"""Malformed payload quarantine tests — schema mismatch / negative / unknown side (MCT-138).

validation_status = MALFORMED + quarantine record emitted.
Quarantine rows do NOT advance the ingest_seq counter — they're side-channel
evidence, not tick.v1.1 data rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from mctrader_market_bithumb.subscribers import (
    QuarantineRecord,
    TransactionTickEmitter,
)

RECEIVED = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _frame(**overrides: object) -> bytes:
    """Build a Bithumb transaction frame with field overrides on the first list entry."""
    entry: dict[str, object] = {
        "symbol": "BTC_KRW",
        "contPrice": "118919000",
        "contQty": "0.001",
        "buySellGb": "1",
        "contDtm": "2026-05-07 20:56:17.158984",
    }
    entry.update(overrides)
    payload = {"type": "transaction", "content": {"list": [entry]}}
    return json.dumps(payload).encode("utf-8")


# ── schema mismatch — missing field ───────────────────────────────────────


def test_missing_contPrice_quarantined() -> None:  # noqa: N802
    emitter = TransactionTickEmitter()
    raw = json.dumps({
        "type": "transaction",
        "content": {"list": [{"symbol": "BTC_KRW", "contQty": "1", "buySellGb": "1",
                              "contDtm": "2026-05-07 20:56:17.158984"}]},
    }).encode("utf-8")
    rows = emitter.process(raw_bytes=raw, received_at=RECEIVED)
    assert rows == []
    qs = emitter.drain_quarantine()
    assert len(qs) == 1
    assert isinstance(qs[0], QuarantineRecord)
    assert qs[0].reason == "SCHEMA_MISMATCH"


def test_missing_list_quarantined() -> None:
    emitter = TransactionTickEmitter()
    raw = b'{"type": "transaction", "content": {}}'
    rows = emitter.process(raw_bytes=raw, received_at=RECEIVED)
    assert rows == []
    qs = emitter.drain_quarantine()
    assert len(qs) == 1
    assert qs[0].reason == "SCHEMA_MISMATCH"


def test_invalid_json_quarantined() -> None:
    emitter = TransactionTickEmitter()
    rows = emitter.process(raw_bytes=b"not a json {{{", received_at=RECEIVED)
    assert rows == []
    qs = emitter.drain_quarantine()
    assert len(qs) == 1
    assert qs[0].reason == "INVALID_JSON"


# ── negative / zero price | qty ───────────────────────────────────────────


def test_negative_price_quarantined() -> None:
    emitter = TransactionTickEmitter()
    rows = emitter.process(raw_bytes=_frame(contPrice="-1"), received_at=RECEIVED)
    assert rows == []
    qs = emitter.drain_quarantine()
    assert len(qs) == 1
    assert qs[0].reason == "INVALID_VALUE"


def test_zero_price_quarantined() -> None:
    emitter = TransactionTickEmitter()
    rows = emitter.process(raw_bytes=_frame(contPrice="0"), received_at=RECEIVED)
    assert rows == []
    qs = emitter.drain_quarantine()
    assert len(qs) == 1
    assert qs[0].reason == "INVALID_VALUE"


def test_negative_qty_quarantined() -> None:
    emitter = TransactionTickEmitter()
    rows = emitter.process(raw_bytes=_frame(contQty="-0.5"), received_at=RECEIVED)
    assert rows == []
    qs = emitter.drain_quarantine()
    assert len(qs) == 1
    assert qs[0].reason == "INVALID_VALUE"


# ── unknown side ──────────────────────────────────────────────────────────


def test_unknown_side_quarantined() -> None:
    emitter = TransactionTickEmitter()
    rows = emitter.process(raw_bytes=_frame(buySellGb="X"), received_at=RECEIVED)
    assert rows == []
    qs = emitter.drain_quarantine()
    assert len(qs) == 1
    assert qs[0].reason == "UNKNOWN_SIDE"


def test_empty_side_quarantined() -> None:
    emitter = TransactionTickEmitter()
    rows = emitter.process(raw_bytes=_frame(buySellGb=""), received_at=RECEIVED)
    assert rows == []
    qs = emitter.drain_quarantine()
    assert len(qs) == 1
    assert qs[0].reason == "UNKNOWN_SIDE"


# ── counter not advanced on malformed ─────────────────────────────────────


def test_malformed_does_not_advance_ingest_seq() -> None:
    """Malformed rows do not consume ingest_seq."""
    emitter = TransactionTickEmitter()
    # 2 malformed → 0 advance
    emitter.process(raw_bytes=_frame(contPrice="-1"), received_at=RECEIVED)
    emitter.process(raw_bytes=_frame(buySellGb="X"), received_at=RECEIVED)
    # Next clean frame must get ingest_seq=0.
    rows = emitter.process(
        raw_bytes=_frame(),
        received_at=RECEIVED,
    )
    assert rows[0].ingest_seq == 0


# ── quarantine record content ─────────────────────────────────────────────


def test_quarantine_record_captures_payload_hash_and_received_at() -> None:
    emitter = TransactionTickEmitter()
    raw = _frame(contPrice="-1")
    emitter.process(raw_bytes=raw, received_at=RECEIVED)
    qs = emitter.drain_quarantine()
    assert len(qs) == 1
    q = qs[0]
    assert q.received_at == RECEIVED
    assert q.raw_bytes == raw
    assert q.payload_hash  # non-empty hash
    assert q.reason == "INVALID_VALUE"


def test_drain_quarantine_empties_buffer() -> None:
    emitter = TransactionTickEmitter()
    emitter.process(raw_bytes=_frame(contPrice="-1"), received_at=RECEIVED)
    assert len(emitter.drain_quarantine()) == 1
    assert emitter.drain_quarantine() == []

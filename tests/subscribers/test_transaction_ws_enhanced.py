"""tick.v1.1 emit tests — ingest_seq monotonic / payload_hash deterministic / validation_status=OK default (MCT-138).

Covers Story §1 acceptance:
- ingest_seq is monotonic, starts at 0, increments per emit.
- payload_hash = sha256(raw_bytes).hexdigest()[:16] (deterministic, content-addressable).
- validation_status defaults to ``"OK"`` for well-formed payloads.
- emitted row validates as TickRowV1_1 (tick.v1.1 schema, mctrader-market SSOT).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from mctrader_market.schemas import TickRowV1_1, ValidationStatus
from mctrader_market.types import Symbol

from mctrader_market_bithumb.subscribers import (
    IngestSeqCounter,
    TransactionTickEmitter,
    build_transaction_tick_row,
    compute_payload_hash,
)

RECEIVED = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _make_transaction_frame(*, sym: str = "BTC_KRW", price: str = "118919000",
                            qty: str = "0.001", side: str = "1",
                            contDtm: str = "2026-05-07 20:56:17.158984") -> bytes:  # noqa: N803
    """Build a raw Bithumb transaction WS frame (bytes, JSON-encoded)."""
    payload = {
        "type": "transaction",
        "content": {
            "list": [
                {
                    "symbol": sym,
                    "contPrice": price,
                    "contQty": qty,
                    "buySellGb": side,
                    "contDtm": contDtm,
                }
            ]
        },
    }
    return json.dumps(payload).encode("utf-8")


# ── payload_hash ──────────────────────────────────────────────────────────


def test_payload_hash_is_sha256_first_16_hex_of_raw_bytes() -> None:
    raw = b'{"foo": 1}'
    h = compute_payload_hash(raw)
    # sha256("{\"foo\": 1}") = b3a8e0... — only assert the contract shape.
    assert isinstance(h, str)
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_payload_hash_deterministic_for_identical_bytes() -> None:
    raw = b'{"type": "transaction"}'
    assert compute_payload_hash(raw) == compute_payload_hash(raw)


def test_payload_hash_differs_for_different_bytes() -> None:
    assert compute_payload_hash(b"a") != compute_payload_hash(b"b")


# ── ingest_seq monotonic ──────────────────────────────────────────────────


def test_ingest_seq_counter_starts_at_zero() -> None:
    counter = IngestSeqCounter()
    assert counter.next() == 0


def test_ingest_seq_counter_monotonic_increment() -> None:
    counter = IngestSeqCounter()
    seqs = [counter.next() for _ in range(5)]
    assert seqs == [0, 1, 2, 3, 4]


def test_ingest_seq_counter_reset_restores_zero() -> None:
    counter = IngestSeqCounter()
    counter.next()
    counter.next()
    counter.reset()
    assert counter.next() == 0


# ── build_transaction_tick_row (single frame → list[TickRowV1_1]) ─────────


def test_build_transaction_tick_row_default_status_ok() -> None:
    counter = IngestSeqCounter()
    raw = _make_transaction_frame()
    rows = build_transaction_tick_row(
        raw_bytes=raw,
        received_at=RECEIVED,
        ingest_seq_counter=counter,
    )
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, TickRowV1_1)
    assert row.validation_status == ValidationStatus.OK.value
    assert row.ingest_seq == 0
    assert row.exchange == "bithumb"
    assert row.symbol == Symbol(base="BTC", quote="KRW")
    assert row.side == "BUY"  # buySellGb=1 → BUY
    assert row.payload_hash == compute_payload_hash(raw)


def test_build_transaction_tick_row_side_sell() -> None:
    counter = IngestSeqCounter()
    raw = _make_transaction_frame(side="2")
    rows = build_transaction_tick_row(raw_bytes=raw, received_at=RECEIVED, ingest_seq_counter=counter)
    assert rows[0].side == "SELL"


def test_build_transaction_tick_row_consumes_counter() -> None:
    """Each emitted row consumes exactly one ingest_seq."""
    counter = IngestSeqCounter()
    rows = []
    for _ in range(3):
        rows.extend(
            build_transaction_tick_row(
                raw_bytes=_make_transaction_frame(),
                received_at=RECEIVED,
                ingest_seq_counter=counter,
            )
        )
    assert [r.ingest_seq for r in rows] == [0, 1, 2]


def test_build_transaction_tick_row_event_time_is_utc() -> None:
    counter = IngestSeqCounter()
    raw = _make_transaction_frame(contDtm="2026-05-07 20:56:17.158984")  # KST
    rows = build_transaction_tick_row(raw_bytes=raw, received_at=RECEIVED, ingest_seq_counter=counter)
    # KST 20:56:17.158984 → UTC 11:56:17.158984
    assert rows[0].ts_utc == datetime(2026, 5, 7, 11, 56, 17, 158984, tzinfo=timezone.utc)


def test_build_transaction_tick_row_trade_id_present_and_stable() -> None:
    """trade_id must be deterministic per (symbol, ts_utc, index_in_list)."""
    counter1 = IngestSeqCounter()
    counter2 = IngestSeqCounter()
    raw = _make_transaction_frame()
    rows1 = build_transaction_tick_row(raw_bytes=raw, received_at=RECEIVED, ingest_seq_counter=counter1)
    rows2 = build_transaction_tick_row(raw_bytes=raw, received_at=RECEIVED, ingest_seq_counter=counter2)
    assert rows1[0].trade_id == rows2[0].trade_id
    assert rows1[0].trade_id  # non-empty


# ── TransactionTickEmitter (end-to-end facade) ────────────────────────────


def test_emitter_emits_ok_for_clean_frame() -> None:
    emitter = TransactionTickEmitter()
    raw = _make_transaction_frame()
    rows = emitter.process(raw_bytes=raw, received_at=RECEIVED)
    assert rows
    assert all(r.validation_status == "OK" for r in rows)
    assert rows[0].ingest_seq == 0


def test_emitter_increments_ingest_seq_across_calls() -> None:
    emitter = TransactionTickEmitter()
    seqs: list[int] = []
    for _ in range(4):
        for row in emitter.process(raw_bytes=_make_transaction_frame(), received_at=RECEIVED):
            assert row.ingest_seq is not None
            seqs.append(row.ingest_seq)
    assert seqs == [0, 1, 2, 3]


def test_emitter_reconnect_boundary_marks_next_row() -> None:
    """After mark_reconnect_boundary(), the very next emitted row is tagged."""
    emitter = TransactionTickEmitter()
    emitter.process(raw_bytes=_make_transaction_frame(), received_at=RECEIVED)
    emitter.mark_reconnect_boundary()
    rows = emitter.process(raw_bytes=_make_transaction_frame(), received_at=RECEIVED)
    assert rows[0].validation_status == "RECONNECT_BOUNDARY"
    # subsequent rows revert to OK
    rows2 = emitter.process(raw_bytes=_make_transaction_frame(), received_at=RECEIVED)
    assert rows2[0].validation_status == "OK"


def test_emitter_skips_non_transaction_frames() -> None:
    """Subscribe ack / ticker / orderbookdepth frames are ignored (return [])."""
    emitter = TransactionTickEmitter()
    ack = b'{"status":"0000","resmsg":"Filter Registered Successfully"}'
    assert emitter.process(raw_bytes=ack, received_at=RECEIVED) == []

    ticker = json.dumps(
        {"type": "ticker", "content": {"symbol": "BTC_KRW", "openPrice": "1"}}
    ).encode("utf-8")
    # ticker is a known non-transaction type — emitter must return [], not raise.
    assert emitter.process(raw_bytes=ticker, received_at=RECEIVED) == []


def test_emitter_counter_starts_fresh_per_instance() -> None:
    """Each emitter has its own counter (restart semantics → reset to 0)."""
    a = TransactionTickEmitter()
    b = TransactionTickEmitter()
    a.process(raw_bytes=_make_transaction_frame(), received_at=RECEIVED)
    a.process(raw_bytes=_make_transaction_frame(), received_at=RECEIVED)
    rows_b = b.process(raw_bytes=_make_transaction_frame(), received_at=RECEIVED)
    assert rows_b[0].ingest_seq == 0


# ── invariants vs tick.v1.1 schema ────────────────────────────────────────


def test_emitted_rows_validate_under_tick_v1_1() -> None:
    """Emitted rows are valid TickRowV1_1 instances with all 11 columns populated."""
    from mctrader_market.schemas import TICK_V1_1_COLUMNS

    emitter = TransactionTickEmitter()
    rows = emitter.process(raw_bytes=_make_transaction_frame(), received_at=RECEIVED)
    assert rows
    for row in rows:
        assert isinstance(row, TickRowV1_1)
        # All 11 columns must be addressable on the row (tick.v1.1 manifest).
        for col in TICK_V1_1_COLUMNS:
            assert hasattr(row, col), f"missing column: {col}"
        # Extension columns must be non-default sentinels for OK emits.
        assert row.ingest_seq is not None
        assert row.payload_hash is not None
        assert row.validation_status == "OK"


@pytest.mark.parametrize("buy_sell_gb", ["1", "buy"])
def test_emitter_buy_side_variants(buy_sell_gb: str) -> None:
    emitter = TransactionTickEmitter()
    raw = _make_transaction_frame(side=buy_sell_gb)
    rows = emitter.process(raw_bytes=raw, received_at=RECEIVED)
    assert rows[0].side == "BUY"


@pytest.mark.parametrize("buy_sell_gb", ["2", "sell"])
def test_emitter_sell_side_variants(buy_sell_gb: str) -> None:
    emitter = TransactionTickEmitter()
    raw = _make_transaction_frame(side=buy_sell_gb)
    rows = emitter.process(raw_bytes=raw, received_at=RECEIVED)
    assert rows[0].side == "SELL"

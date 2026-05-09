"""ws_mapping tests — JSONL fixture replay → typed event."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mctrader_market.types import Symbol

from mctrader_market_bithumb.exceptions import SchemaMismatchError
from mctrader_market_bithumb.ws_events import (
    OrderbookDeltaEvent,
    TickerEvent,
    TransactionEvent,
)
from mctrader_market_bithumb.ws_mapping import normalize_message

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "bithumb"
RECEIVED = datetime(2025, 4, 25, 0, 0, tzinfo=timezone.utc)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_ticker_jsonl_replay_typed_event() -> None:
    rows = _read_jsonl(FIXTURE_DIR / "ws_ticker_BTC_KRW.jsonl")
    events = [normalize_message(r, received_at=RECEIVED) for r in rows]
    assert all(isinstance(e, TickerEvent) for e in events)
    assert events[0].symbol == Symbol(base="BTC", quote="KRW")
    assert events[0].close == Decimal("100200000.000000000000000000")
    assert events[0].high == Decimal("100500000.000000000000000000")


def test_transaction_jsonl_replay_typed_event() -> None:
    """Live Bithumb envelope: contDtm = KST naive datetime string with microseconds."""
    rows = _read_jsonl(FIXTURE_DIR / "ws_transaction_BTC_KRW.jsonl")
    events = [normalize_message(r, received_at=RECEIVED) for r in rows]
    assert all(isinstance(e, TransactionEvent) for e in events)
    assert events[0].price == Decimal("118919000.000000000000000000")
    assert events[0].side == "sell"  # buySellGb=2 = sell
    assert events[1].side == "buy"   # buySellGb=1 = buy
    # KST 2026-05-07 20:56:17.158984 → UTC 2026-05-07T11:56:17.158984
    assert events[0].event_time == datetime(2026, 5, 7, 11, 56, 17, 158984, tzinfo=timezone.utc)


def test_orderbookdepth_jsonl_replay_typed_event() -> None:
    """Live Bithumb envelope: orderbookdepth — symbol on list entries, content.datetime us-epoch."""
    rows = _read_jsonl(FIXTURE_DIR / "ws_orderbookdepth_BTC_KRW.jsonl")
    events = [normalize_message(r, received_at=RECEIVED) for r in rows]
    assert all(isinstance(e, OrderbookDeltaEvent) for e in events)
    assert events[0].symbol == Symbol(base="BTC", quote="KRW")
    assert len(events[0].changes) == 3
    assert events[0].changes[0].side == "ask"
    assert events[0].changes[0].price == Decimal("118955000")
    assert events[0].changes[1].side == "bid"
    # us-epoch 1778154976506519 / 1_000_000 = 1778154976.506519 → UTC 2026-05-07T11:56:16.506519
    assert events[0].event_time == datetime(2026, 5, 7, 11, 56, 16, 506519, tzinfo=timezone.utc)


def test_unknown_type_raises_schema_mismatch() -> None:
    with pytest.raises(SchemaMismatchError):
        normalize_message({"type": "private_account", "content": {"symbol": "BTC_KRW"}}, received_at=RECEIVED)


def test_missing_content_raises() -> None:
    with pytest.raises(SchemaMismatchError):
        normalize_message({"type": "ticker"}, received_at=RECEIVED)


def test_subscribe_ack_returns_none() -> None:
    """Messages without 'type' are non-data ack and skipped silently."""
    assert normalize_message({"status": "0000", "resmsg": "Filter Registered Successfully"}, received_at=RECEIVED) is None


def test_parse_event_time_us_epoch_string() -> None:
    """orderbookdepth content.datetime is a microsecond-epoch string (16 digits)."""
    from mctrader_market_bithumb.ws_mapping import _parse_event_time

    dt = _parse_event_time("1778154976506519")
    assert dt == datetime(2026, 5, 7, 11, 56, 16, 506519, tzinfo=timezone.utc)


def test_parse_event_time_kst_naive_string() -> None:
    """transaction contDtm is a KST naive datetime string."""
    from mctrader_market_bithumb.ws_mapping import _parse_event_time

    dt = _parse_event_time("2026-05-07 20:56:17.158984")
    assert dt == datetime(2026, 5, 7, 11, 56, 17, 158984, tzinfo=timezone.utc)


def test_parse_event_time_ms_epoch_legacy() -> None:
    """Legacy fixture format: 13-digit ms-epoch string remains supported."""
    from mctrader_market_bithumb.ws_mapping import _parse_event_time

    dt = _parse_event_time("1745539210000")
    assert dt == datetime(2025, 4, 25, 0, 0, 10, tzinfo=timezone.utc)


# ── orderbooksnapshot (MCT-104 §D14, wiretap-confirmed 2026-05-09) ────────────

def test_orderbooksnapshot_list_format() -> None:
    """Wiretap payload: asks/bids as [[price, qty] x 30] — list-of-lists format."""
    from mctrader_market_bithumb.ws_events import OrderbookSnapshotEvent

    raw = {
        "type": "orderbooksnapshot",
        "content": {
            "symbol": "BTC_KRW",
            "datetime": "1778154976506519",  # 16-digit micro-epoch
            "asks": [
                ["119000000", "0.5"],
                ["119100000", "1.2"],
            ],
            "bids": [
                ["118900000", "0.3"],
                ["118800000", "2.1"],
            ],
        },
    }
    event = normalize_message(raw, received_at=RECEIVED)
    assert isinstance(event, OrderbookSnapshotEvent)
    assert event.symbol == Symbol(base="BTC", quote="KRW")
    assert event.event_time == datetime(2026, 5, 7, 11, 56, 16, 506519, tzinfo=timezone.utc)
    assert len(event.asks) == 2
    assert len(event.bids) == 2
    assert event.asks[0].price == Decimal("119000000")
    assert event.asks[0].quantity == Decimal("0.5")
    assert event.bids[0].price == Decimal("118900000")
    assert event.bids[0].quantity == Decimal("0.3")


def test_orderbooksnapshot_dict_format() -> None:
    """Forward-compat: asks/bids as [{'price':..,'quantity':..}] dict format."""
    from mctrader_market_bithumb.ws_events import OrderbookSnapshotEvent

    raw = {
        "type": "orderbooksnapshot",
        "content": {
            "symbol": "ETH_KRW",
            "datetime": "1778154976506519",
            "asks": [{"price": "5000000", "quantity": "1.0"}],
            "bids": [{"price": "4990000", "quantity": "2.0"}],
        },
    }
    event = normalize_message(raw, received_at=RECEIVED)
    assert isinstance(event, OrderbookSnapshotEvent)
    assert event.symbol == Symbol(base="ETH", quote="KRW")
    assert event.asks[0].price == Decimal("5000000")


def test_orderbooksnapshot_missing_symbol_raises() -> None:
    raw = {
        "type": "orderbooksnapshot",
        "content": {
            "datetime": "1778154976506519",
            "asks": [],
            "bids": [],
        },
    }
    with pytest.raises(SchemaMismatchError):
        normalize_message(raw, received_at=RECEIVED)


def test_orderbooksnapshot_camelcase_rejected() -> None:
    """camelCase 'orderbookSnapshot' must be rejected as unknown type (wiretap D-mode)."""
    with pytest.raises(SchemaMismatchError):
        normalize_message(
            {"type": "orderbookSnapshot", "content": {"symbol": "BTC_KRW"}},
            received_at=RECEIVED,
        )


def test_ticker_missing_price_field_raises_schema_mismatch() -> None:
    """Ticker message with a missing required price field must raise SchemaMismatchError, not return Decimal('0')."""
    raw = {
        "type": "ticker",
        "content": {
            "symbol": "BTC_KRW",
            "openPrice": "100000000",
            "highPrice": "100500000",
            "lowPrice": "99800000",
            # closePrice intentionally omitted
            "volume": "10.5",
        },
    }
    with pytest.raises(SchemaMismatchError):
        normalize_message(raw, received_at=RECEIVED)


def test_orderbookdepth_unknown_ordertype_raises_schema_mismatch() -> None:
    """orderbookdepth entry with an unknown orderType must raise SchemaMismatchError."""
    raw = {
        "type": "orderbookdepth",
        "content": {
            "list": [
                {
                    "symbol": "BTC_KRW",
                    "orderType": "unknown_side",
                    "price": "100000000",
                    "quantity": "0.5",
                    "datetime": "1778154976506519",
                },
            ],
        },
    }
    with pytest.raises(SchemaMismatchError):
        normalize_message(raw, received_at=RECEIVED)

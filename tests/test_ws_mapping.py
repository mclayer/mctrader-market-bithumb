"""ws_mapping tests — JSONL fixture replay → typed event."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mctrader_market.types import Symbol

from mctrader_market_bithumb.exceptions import SchemaMismatchError
from mctrader_market_bithumb.ws_events import TickerEvent, TransactionEvent
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
    rows = _read_jsonl(FIXTURE_DIR / "ws_transaction_BTC_KRW.jsonl")
    events = [normalize_message(r, received_at=RECEIVED) for r in rows]
    assert all(isinstance(e, TransactionEvent) for e in events)
    assert events[0].price == Decimal("100200000.000000000000000000")
    assert events[0].side == "buy"
    assert events[1].side == "sell"


def test_unknown_type_raises_schema_mismatch() -> None:
    with pytest.raises(SchemaMismatchError):
        normalize_message({"type": "private_account", "content": {"symbol": "BTC_KRW"}}, received_at=RECEIVED)


def test_missing_content_raises() -> None:
    with pytest.raises(SchemaMismatchError):
        normalize_message({"type": "ticker"}, received_at=RECEIVED)


def test_subscribe_ack_returns_none() -> None:
    """Messages without 'type' are non-data ack and skipped silently."""
    assert normalize_message({"status": "0000", "resmsg": "Filter Registered Successfully"}, received_at=RECEIVED) is None

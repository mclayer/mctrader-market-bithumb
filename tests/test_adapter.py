"""BithumbCandleProvider + BithumbOrderBookProvider contract tests — Protocol satisfaction + envelope parsing + coverage check."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from mctrader_market.providers import CandleProvider, OrderBookProvider
from mctrader_market.orderbook import OrderBookModel
from mctrader_market.types import Symbol, Timeframe

from mctrader_market_bithumb.adapter import BithumbCandleProvider, BithumbOrderBookProvider
from mctrader_market_bithumb.client import (
    BithumbHttpClient,
    RateLimitConfig,
    RetryConfig,
)
from mctrader_market_bithumb.exceptions import (
    InsufficientCoverageError,
    SchemaMismatchError,
)

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "bithumb" / "public_candlestick_BTC_KRW_1h.json"


def _adapter_with_payload(payload: dict | str) -> BithumbCandleProvider:
    body = payload if isinstance(payload, str) else json.dumps(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, str):
            return httpx.Response(200, text=body)
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = BithumbHttpClient(
        client=httpx.Client(base_url="https://api.bithumb.com/public", transport=transport),
        rate_limit=RateLimitConfig(rate_per_second=1000, burst=100),
        retry=RetryConfig(max_attempts=1, backoff_base_seconds=0.0),
        sleep=lambda _: None,
    )
    return BithumbCandleProvider(client=client)


def test_provider_satisfies_candle_provider_protocol() -> None:
    adapter = _adapter_with_payload({"status": "0000", "data": []})
    assert isinstance(adapter, CandleProvider)


def test_get_candles_with_recorded_fixture() -> None:
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter = _adapter_with_payload(payload)

    start = datetime(2025, 4, 25, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=5)

    candles = adapter.get_candles(Symbol(base="BTC", quote="KRW"), Timeframe.H1, start, end)
    assert len(candles) == 5
    assert candles[0].ts_utc == datetime(2025, 4, 25, 0, 0, tzinfo=timezone.utc)
    # IDX 2 (close=100200000) vs IDX 3 (high=100500000) — Decimal38_18 quantizes to 18 places
    assert candles[0].close == Decimal("100200000")
    assert candles[0].high == Decimal("100500000")
    assert candles[0].quarantine_reason == "VALUE_ABSENCE_BITHUMB"


def test_half_open_interval_filtering() -> None:
    payload = json.loads(FIXTURE_PATH.read_text())
    adapter = _adapter_with_payload(payload)

    start = datetime(2025, 4, 25, 1, 0, tzinfo=timezone.utc)
    end = datetime(2025, 4, 25, 4, 0, tzinfo=timezone.utc)

    candles = adapter.get_candles(Symbol(base="BTC", quote="KRW"), Timeframe.H1, start, end)
    assert len(candles) == 3
    for c in candles:
        assert start <= c.ts_utc < end


def test_envelope_status_non_ok_raises_schema_mismatch() -> None:
    adapter = _adapter_with_payload({"status": "5500", "message": "error"})
    with pytest.raises(SchemaMismatchError, match="non-OK status"):
        adapter.get_candles(
            Symbol(base="BTC", quote="KRW"),
            Timeframe.H1,
            datetime(2025, 4, 25, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 4, 25, 5, 0, tzinfo=timezone.utc),
        )


def test_envelope_data_not_list_raises() -> None:
    adapter = _adapter_with_payload({"status": "0000", "data": "not a list"})
    with pytest.raises(SchemaMismatchError, match="data must be list"):
        adapter.get_candles(
            Symbol(base="BTC", quote="KRW"),
            Timeframe.H1,
            datetime(2025, 4, 25, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 4, 25, 5, 0, tzinfo=timezone.utc),
        )


def test_empty_data_raises_insufficient_coverage() -> None:
    adapter = _adapter_with_payload({"status": "0000", "data": []})
    with pytest.raises(InsufficientCoverageError, match="empty result"):
        adapter.get_candles(
            Symbol(base="BTC", quote="KRW"),
            Timeframe.H1,
            datetime(2025, 4, 25, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 4, 25, 5, 0, tzinfo=timezone.utc),
        )


# ── BithumbOrderBookProvider tests ─────────────────────────────────────────────

def _orderbook_provider_with_payload(payload: dict) -> BithumbOrderBookProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = BithumbHttpClient(
        client=httpx.Client(base_url="https://api.bithumb.com/public", transport=transport),
        rate_limit=RateLimitConfig(rate_per_second=1000, burst=100),
        retry=RetryConfig(max_attempts=1, backoff_base_seconds=0.0),
        sleep=lambda _: None,
    )
    return BithumbOrderBookProvider(client=client)


def test_orderbook_provider_satisfies_protocol() -> None:
    """BithumbOrderBookProvider must satisfy the OrderBookProvider protocol (runtime_checkable)."""
    provider = _orderbook_provider_with_payload(
        {"status": "0000", "data": {"bids": [], "asks": []}}
    )
    assert isinstance(provider, OrderBookProvider)


def test_orderbook_provider_parses_rest_response() -> None:
    """Mock REST orderbook response with bids/asks must be parsed into an OrderBookModel correctly."""
    payload = {
        "status": "0000",
        "data": {
            "bids": [
                {"price": "100000000", "quantity": "0.5"},
                {"price": "99900000", "quantity": "1.2"},
            ],
            "asks": [
                {"price": "100100000", "quantity": "0.3"},
                {"price": "100200000", "quantity": "2.0"},
            ],
        },
    }
    provider = _orderbook_provider_with_payload(payload)
    result = provider.get_orderbook(Symbol(base="BTC", quote="KRW"))

    assert isinstance(result, OrderBookModel)
    assert result.exchange == "bithumb"
    assert result.symbol == Symbol(base="BTC", quote="KRW")
    assert len(result.bids) == 2
    assert len(result.asks) == 2
    assert result.bids[0].price == Decimal("100000000")
    assert result.bids[0].quantity == Decimal("0.5")
    assert result.asks[0].price == Decimal("100100000")
    assert result.asks[0].quantity == Decimal("0.3")

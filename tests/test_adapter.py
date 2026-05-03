"""BithumbCandleProvider contract tests — Protocol satisfaction + envelope parsing + coverage check."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from mctrader_market.providers import CandleProvider
from mctrader_market.types import Symbol, Timeframe

from mctrader_market_bithumb.adapter import BithumbCandleProvider
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

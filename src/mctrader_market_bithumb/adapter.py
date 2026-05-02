"""BithumbCandleProvider — implements ``mctrader_market.providers.CandleProvider``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mctrader_market.candle import CandleModel
from mctrader_market.types import Symbol, Timeframe

from mctrader_market_bithumb.client import BithumbHttpClient
from mctrader_market_bithumb.exceptions import (
    InsufficientCoverageError,
    SchemaMismatchError,
)
from mctrader_market_bithumb.mapping import (
    TIMEFRAME_TO_BITHUMB,
    normalize_row,
    symbol_to_bithumb_path,
)


def _parse_envelope(payload: Any) -> list[list]:
    """Bithumb response envelope: ``{"status": "0000", "data": [[ts, open, close, high, low, vol], ...]}``."""
    if not isinstance(payload, dict):
        raise SchemaMismatchError(f"envelope must be dict, got {type(payload).__name__}")
    status = payload.get("status")
    if status != "0000":
        raise SchemaMismatchError(f"non-OK status: {status!r}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise SchemaMismatchError(f"data must be list, got {type(data).__name__}")
    return data


class BithumbCandleProvider:
    """Public Bithumb OHLCV provider — eager single-call (MCT-12 7-day 1h scope)."""

    def __init__(self, client: BithumbHttpClient | None = None) -> None:
        self._client = client or BithumbHttpClient()

    def get_candles(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[CandleModel]:
        path = symbol_to_bithumb_path(symbol)
        chart_interval = TIMEFRAME_TO_BITHUMB[timeframe]
        raw_payload = self._client.get_candlestick(path, chart_interval)
        rows = _parse_envelope(raw_payload)
        candles = [normalize_row(r, exchange="bithumb", symbol=symbol, timeframe=timeframe) for r in rows]
        candles.sort(key=lambda c: c.ts_utc)
        filtered = [c for c in candles if start <= c.ts_utc < end]
        self._verify_coverage(filtered, start, end, timeframe)
        return filtered

    @staticmethod
    def _verify_coverage(
        candles: list[CandleModel],
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
    ) -> None:
        if not candles:
            raise InsufficientCoverageError(f"empty result for [{start}, {end})")
        first_gap = candles[0].ts_utc - start
        if first_gap > timeframe.delta:
            raise InsufficientCoverageError(
                f"first candle {candles[0].ts_utc} outside requested start={start} (gap={first_gap})"
            )
        last_gap = end - candles[-1].ts_utc
        if last_gap > timeframe.delta * 2:
            raise InsufficientCoverageError(
                f"last candle {candles[-1].ts_utc} too far before end={end} (gap={last_gap})"
            )

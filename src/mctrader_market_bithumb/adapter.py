"""BithumbCandleProvider + BithumbOrderBookProvider — implements mctrader_market providers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from mctrader_market.candle import CandleModel
from mctrader_market.orderbook import OrderBookLevel, OrderBookModel
from mctrader_market.types import Symbol, Timeframe

from mctrader_market_bithumb.client import BithumbHttpClient
from mctrader_market_bithumb.exceptions import (
    BithumbApiError,
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
        raise BithumbApiError(f"non-OK status: {status!r} message={payload.get('message', '')!r}")
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


def _parse_orderbook_envelope(payload: Any) -> dict:
    """Bithumb orderbook envelope: ``{"status": "0000", "data": {"bids": [...], "asks": [...], ...}}``."""
    if not isinstance(payload, dict):
        raise SchemaMismatchError(f"orderbook envelope must be dict, got {type(payload).__name__}")
    status = payload.get("status")
    if status != "0000":
        raise BithumbApiError(f"non-OK status: {status!r} message={payload.get('message', '')!r}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise SchemaMismatchError(f"orderbook data must be dict, got {type(data).__name__}")
    return data


def _parse_orderbook_levels(raw_levels: Any, side: str) -> tuple[OrderBookLevel, ...]:
    """Parse a list of ``{"price": str, "quantity": str}`` dicts into ``OrderBookLevel`` tuples."""
    if not isinstance(raw_levels, list):
        raise SchemaMismatchError(f"orderbook {side} must be list, got {type(raw_levels).__name__}")
    levels: list[OrderBookLevel] = []
    for entry in raw_levels:
        if not isinstance(entry, dict):
            raise SchemaMismatchError(f"orderbook {side} entry must be dict, got {type(entry).__name__}")
        try:
            levels.append(
                OrderBookLevel(
                    price=Decimal(str(entry["price"])),
                    quantity=Decimal(str(entry["quantity"])),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaMismatchError(f"orderbook {side} entry parse failed: {exc}") from exc
    return tuple(levels)


class BithumbOrderBookProvider:
    """Public Bithumb orderbook snapshot provider — implements ``OrderBookProvider``.

    Calls ``GET /orderbook/{symbol_path}`` and maps the response to ``OrderBookModel``.
    The ``ts_utc`` is set to the current UTC time at the point of the response, as Bithumb's
    public orderbook endpoint does not include a server-side timestamp in the data envelope.
    """

    def __init__(self, client: BithumbHttpClient | None = None) -> None:
        self._client = client or BithumbHttpClient()

    def get_orderbook(self, symbol: Symbol) -> OrderBookModel:
        """Fetch a full orderbook snapshot for the given symbol.

        Raises :class:`BithumbApiError` on non-"0000" envelope status or HTTP failures.
        Raises :class:`SchemaMismatchError` when the response structure is unexpected.
        """
        path = symbol_to_bithumb_path(symbol)
        raw_payload = self._client.get_orderbook(path)
        data = _parse_orderbook_envelope(raw_payload)
        bids = _parse_orderbook_levels(data.get("bids", []), "bids")
        asks = _parse_orderbook_levels(data.get("asks", []), "asks")
        return OrderBookModel(
            ts_utc=datetime.now(timezone.utc),
            exchange="bithumb",
            symbol=symbol,
            bids=bids,
            asks=asks,
        )

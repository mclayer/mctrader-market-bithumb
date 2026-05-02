"""Bithumb response normalization — explicit positional constants + symbol mapping (ADR-009 D3)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from mctrader_market.candle import CandleModel
from mctrader_market.types import Symbol, Timeframe

from mctrader_market_bithumb.exceptions import SchemaMismatchError

# Bithumb response array order — INDEX 2 = close (NOT high).
IDX_TS_MS = 0
IDX_OPEN = 1
IDX_CLOSE = 2
IDX_HIGH = 3
IDX_LOW = 4
IDX_VOLUME = 5
ROW_LENGTH = 6

# Bithumb chart_intervals → mctrader Timeframe canonical
TIMEFRAME_TO_BITHUMB: dict[Timeframe, str] = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "24h",
}


def symbol_to_bithumb_path(symbol: Symbol) -> str:
    """``Symbol(base="BTC", quote="KRW")`` → ``"BTC_KRW"`` (Bithumb endpoint segment)."""
    return f"{symbol.base}_{symbol.quote}"


def bithumb_path_to_symbol(path: str) -> Symbol:
    """``"BTC_KRW"`` → ``Symbol(base="BTC", quote="KRW")``."""
    if "_" not in path:
        raise ValueError(f"invalid Bithumb symbol path: {path!r}")
    base, _, quote = path.partition("_")
    if not base or not quote:
        raise ValueError(f"invalid Bithumb symbol path: {path!r}")
    return Symbol(base=base.upper(), quote=quote.upper())


def epoch_ms_to_utc(ts_ms: int | float) -> datetime:
    """Bithumb ``timestamp_ms`` → timezone-aware UTC datetime."""
    return datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc)


def normalize_row(
    row: list,
    *,
    exchange: str,
    symbol: Symbol,
    timeframe: Timeframe,
) -> CandleModel:
    """Normalize a single Bithumb candle row to ``CandleModel`` (ADR-009 v1).

    ``value`` (거래대금 KRW) is always ``None`` for Bithumb response — caller (storage) must
    treat ``quarantine_reason="VALUE_ABSENCE_BITHUMB"`` as the quarantine signal per ADR-009 D3.
    """
    if not isinstance(row, (list, tuple)):
        raise SchemaMismatchError(f"row must be list/tuple, got {type(row).__name__}")
    if len(row) != ROW_LENGTH:
        raise SchemaMismatchError(f"expected {ROW_LENGTH} fields, got {len(row)}")
    try:
        return CandleModel(
            ts_utc=epoch_ms_to_utc(row[IDX_TS_MS]),
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            open=Decimal(str(row[IDX_OPEN])),
            high=Decimal(str(row[IDX_HIGH])),
            low=Decimal(str(row[IDX_LOW])),
            close=Decimal(str(row[IDX_CLOSE])),
            volume=Decimal(str(row[IDX_VOLUME])),
            value=None,
            quarantine_reason="VALUE_ABSENCE_BITHUMB",
        )
    except (TypeError, ValueError) as exc:
        raise SchemaMismatchError(f"row parse failed: {exc}") from exc

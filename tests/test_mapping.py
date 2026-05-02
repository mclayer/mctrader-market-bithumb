"""Bithumb normalization tests — explicit positional constants + Symbol mapping (ADR-009 D3)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mctrader_market.types import Symbol, Timeframe

from mctrader_market_bithumb.exceptions import SchemaMismatchError
from mctrader_market_bithumb.mapping import (
    IDX_CLOSE,
    IDX_HIGH,
    IDX_LOW,
    IDX_OPEN,
    IDX_TS_MS,
    IDX_VOLUME,
    bithumb_path_to_symbol,
    epoch_ms_to_utc,
    normalize_row,
    symbol_to_bithumb_path,
)


class TestIndexConstants:
    def test_close_at_index_2_not_high(self) -> None:
        """CRITICAL: Bithumb position 2 = close (not high)."""
        assert IDX_CLOSE == 2
        assert IDX_HIGH == 3

    def test_all_indices_distinct(self) -> None:
        indices = {IDX_TS_MS, IDX_OPEN, IDX_CLOSE, IDX_HIGH, IDX_LOW, IDX_VOLUME}
        assert len(indices) == 6
        assert indices == {0, 1, 2, 3, 4, 5}


class TestSymbolMapping:
    def test_to_path(self) -> None:
        sym = Symbol(base="BTC", quote="KRW")
        assert symbol_to_bithumb_path(sym) == "BTC_KRW"

    def test_from_path(self) -> None:
        assert bithumb_path_to_symbol("BTC_KRW") == Symbol(base="BTC", quote="KRW")

    def test_roundtrip(self) -> None:
        sym = Symbol(base="ETH", quote="KRW")
        path = symbol_to_bithumb_path(sym)
        assert bithumb_path_to_symbol(path) == sym

    def test_invalid_path(self) -> None:
        with pytest.raises(ValueError):
            bithumb_path_to_symbol("BTCKRW")
        with pytest.raises(ValueError):
            bithumb_path_to_symbol("_KRW")


class TestEpochConversion:
    def test_utc_aware(self) -> None:
        dt = epoch_ms_to_utc(1745539200000)
        assert dt.tzinfo == timezone.utc
        assert dt == datetime(2025, 4, 25, 0, 0, tzinfo=timezone.utc)


class TestNormalizeRow:
    SYMBOL = Symbol(base="BTC", quote="KRW")

    def test_normalizes_canonical_row(self) -> None:
        row = [1745539200000, "100000000.00", "100200000.00", "100500000.00", "99500000.00", "1.5"]
        candle = normalize_row(row, exchange="bithumb", symbol=self.SYMBOL, timeframe=Timeframe.H1)
        assert candle.ts_utc == datetime(2025, 4, 25, 0, 0, tzinfo=timezone.utc)
        assert candle.open == Decimal("100000000.00")
        assert candle.close == Decimal("100200000.00")  # IDX 2
        assert candle.high == Decimal("100500000.00")  # IDX 3
        assert candle.low == Decimal("99500000.00")
        assert candle.volume == Decimal("1.5")

    def test_value_absence_quarantine_signal(self) -> None:
        row = [1745539200000, "100000000.00", "100200000.00", "100500000.00", "99500000.00", "1.5"]
        candle = normalize_row(row, exchange="bithumb", symbol=self.SYMBOL, timeframe=Timeframe.H1)
        assert candle.value is None
        assert candle.quarantine_reason == "VALUE_ABSENCE_BITHUMB"

    def test_decimal_precision_preserved(self) -> None:
        row = [
            1745539200000,
            "50000000.123456789012345678",
            "50000100.000000000000000001",
            "50001000.000000000000000000",
            "49999000.000000000000000000",
            "0.00000001",
        ]
        candle = normalize_row(row, exchange="bithumb", symbol=self.SYMBOL, timeframe=Timeframe.H1)
        assert candle.open == Decimal("50000000.123456789012345678")
        assert candle.close == Decimal("50000100.000000000000000001")

    def test_short_row_raises_schema_mismatch(self) -> None:
        with pytest.raises(SchemaMismatchError, match="expected 6"):
            normalize_row([1, 2, 3], exchange="bithumb", symbol=self.SYMBOL, timeframe=Timeframe.H1)

    def test_long_row_raises_schema_mismatch(self) -> None:
        with pytest.raises(SchemaMismatchError, match="expected 6"):
            normalize_row(
                [1745539200000, "1", "2", "3", "4", "5", "extra"],
                exchange="bithumb",
                symbol=self.SYMBOL,
                timeframe=Timeframe.H1,
            )

    def test_non_list_raises(self) -> None:
        with pytest.raises(SchemaMismatchError):
            normalize_row("not a list", exchange="bithumb", symbol=self.SYMBOL, timeframe=Timeframe.H1)  # type: ignore[arg-type]

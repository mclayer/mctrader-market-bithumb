"""MarketStream event types — Pydantic v2 boundary, Decimal canonical."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mctrader_market.types import Decimal38_18, Symbol, UTCDateTime


class _BaseEvent(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)
    exchange: str
    symbol: Symbol
    event_time: UTCDateTime
    received_at: UTCDateTime
    raw: dict[str, Any]


class TickerEvent(_BaseEvent):
    kind: Literal["ticker"] = "ticker"
    open: Decimal38_18
    high: Decimal38_18
    low: Decimal38_18
    close: Decimal38_18
    volume: Decimal38_18
    chg_rate: Decimal | None = None

    @field_validator("chg_rate", mode="before")
    @classmethod
    def _validate_chg_rate(cls, v: object) -> object:
        if v is None:
            return v
        if isinstance(v, float):
            raise ValueError("float not allowed for chg_rate; use Decimal or str")
        if isinstance(v, bool):
            raise ValueError("bool not allowed for chg_rate")
        if isinstance(v, int):
            return Decimal(v)
        if isinstance(v, str):
            if not v.strip():
                raise ValueError("whitespace-only string not allowed for chg_rate")
            try:
                d = Decimal(v.strip())
            except InvalidOperation as exc:
                raise ValueError(f"invalid Decimal string for chg_rate: {v!r}") from exc
            if d.is_nan() or not d.is_finite():
                raise ValueError(f"NaN/Inf not allowed for chg_rate: {v!r}")
            if len(d.as_tuple().digits) > 38:
                raise ValueError(f"chg_rate exceeds 38 digits: {v!r}")
            return d
        if isinstance(v, Decimal):
            if v.is_nan() or not v.is_finite():
                raise ValueError(f"NaN/Inf not allowed for chg_rate: {v!r}")
            if len(v.as_tuple().digits) > 38:
                raise ValueError(f"chg_rate exceeds 38 digits: {v!r}")
        return v


class _OrderbookLevel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    price: Decimal38_18
    quantity: Decimal38_18


class OrderbookSnapshotEvent(_BaseEvent):
    kind: Literal["orderbook_snapshot"] = "orderbook_snapshot"
    bids: tuple[_OrderbookLevel, ...]
    asks: tuple[_OrderbookLevel, ...]


class _OrderbookChange(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    side: Literal["bid", "ask"]
    price: Decimal38_18
    quantity: Decimal38_18


class OrderbookDeltaEvent(_BaseEvent):
    kind: Literal["orderbook_delta"] = "orderbook_delta"
    changes: tuple[_OrderbookChange, ...]


class TransactionEvent(_BaseEvent):
    kind: Literal["transaction"] = "transaction"
    price: Decimal38_18
    quantity: Decimal38_18
    side: Literal["buy", "sell"]


StreamEvent = Annotated[
    TickerEvent | OrderbookSnapshotEvent | OrderbookDeltaEvent | TransactionEvent,
    Field(discriminator="kind"),
]

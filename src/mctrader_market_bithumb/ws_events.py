"""MarketStream event types — Pydantic v2 boundary, Decimal canonical."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class _OrderbookLevel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    price: Decimal38_18
    quantity: Decimal38_18


class OrderbookSnapshotEvent(_BaseEvent):
    kind: Literal["orderbook_snapshot"] = "orderbook_snapshot"
    bids: list[_OrderbookLevel]
    asks: list[_OrderbookLevel]


class _OrderbookChange(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    side: Literal["bid", "ask"]
    price: Decimal38_18
    quantity: Decimal38_18


class OrderbookDeltaEvent(_BaseEvent):
    kind: Literal["orderbook_delta"] = "orderbook_delta"
    changes: list[_OrderbookChange]


class TransactionEvent(_BaseEvent):
    kind: Literal["transaction"] = "transaction"
    price: Decimal38_18
    quantity: Decimal38_18
    side: Literal["buy", "sell"]


StreamEvent = Annotated[
    TickerEvent | OrderbookSnapshotEvent | OrderbookDeltaEvent | TransactionEvent,
    Field(discriminator="kind"),
]

"""Raw Bithumb WebSocket message dict → typed StreamEvent."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from mctrader_market.types import Symbol

from mctrader_market_bithumb.exceptions import SchemaMismatchError
from mctrader_market_bithumb.mapping import bithumb_path_to_symbol
from mctrader_market_bithumb.ws_events import (
    OrderbookDeltaEvent,
    OrderbookSnapshotEvent,
    StreamEvent,
    TickerEvent,
    TransactionEvent,
    _OrderbookChange,
    _OrderbookLevel,
)


def _parse_event_time(value: object) -> datetime:
    """Bithumb provides string ts in ms or ISO; default = received_at fallback if missing."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
        except ValueError:
            pass
    raise SchemaMismatchError(f"invalid event_time: {value!r}")


def _resolve_symbol(payload_symbol: object) -> Symbol:
    if not isinstance(payload_symbol, str):
        raise SchemaMismatchError(f"symbol must be string, got {type(payload_symbol).__name__}")
    return bithumb_path_to_symbol(payload_symbol)


def normalize_message(raw: dict[str, Any], *, received_at: datetime) -> StreamEvent | None:
    """Convert one Bithumb WebSocket message to a typed event.

    Returns ``None`` for non-data messages (subscribe ack / status / heartbeat).
    Raises :class:`SchemaMismatchError` for malformed data messages.
    """
    if not isinstance(raw, dict):
        raise SchemaMismatchError(f"raw must be dict, got {type(raw).__name__}")

    msg_type = raw.get("type")
    if msg_type is None:
        # subscribe ack / status without type — skip silently
        return None

    content = raw.get("content")
    if not isinstance(content, dict):
        raise SchemaMismatchError(f"missing/invalid content for type={msg_type!r}")

    symbol_raw = content.get("symbol")
    symbol = _resolve_symbol(symbol_raw) if symbol_raw is not None else None

    event_time = (
        _parse_event_time(content.get("date") or content.get("dateTime") or content.get("timestamp"))
        if content.get("date") or content.get("dateTime") or content.get("timestamp")
        else received_at
    )

    if msg_type == "ticker":
        if symbol is None:
            raise SchemaMismatchError("ticker missing symbol")
        return TickerEvent(
            exchange="bithumb",
            symbol=symbol,
            event_time=event_time,
            received_at=received_at,
            open=Decimal(str(content.get("openPrice", "0"))),
            high=Decimal(str(content.get("highPrice", "0"))),
            low=Decimal(str(content.get("lowPrice", "0"))),
            close=Decimal(str(content.get("closePrice", "0"))),
            volume=Decimal(str(content.get("volume", "0"))),
            chg_rate=(
                Decimal(str(content["chgRate"])) if content.get("chgRate") is not None else None
            ),
            raw=raw,
        )

    if msg_type == "orderbookdepth":
        if symbol is None:
            raise SchemaMismatchError("orderbookdepth missing symbol")
        changes_raw = content.get("list") or []
        if not isinstance(changes_raw, list):
            raise SchemaMismatchError("orderbookdepth list must be array")
        changes = [
            _OrderbookChange(
                side="bid" if entry.get("orderType") == "bid" else "ask",
                price=Decimal(str(entry["price"])),
                quantity=Decimal(str(entry["quantity"])),
            )
            for entry in changes_raw
            if isinstance(entry, dict)
        ]
        return OrderbookDeltaEvent(
            exchange="bithumb",
            symbol=symbol,
            event_time=event_time,
            received_at=received_at,
            changes=changes,
            raw=raw,
        )

    if msg_type == "orderbook_snapshot":
        if symbol is None:
            raise SchemaMismatchError("orderbook_snapshot missing symbol")
        bids_raw = content.get("bids") or []
        asks_raw = content.get("asks") or []
        return OrderbookSnapshotEvent(
            exchange="bithumb",
            symbol=symbol,
            event_time=event_time,
            received_at=received_at,
            bids=[
                _OrderbookLevel(price=Decimal(str(b["price"])), quantity=Decimal(str(b["quantity"])))
                for b in bids_raw
                if isinstance(b, dict)
            ],
            asks=[
                _OrderbookLevel(price=Decimal(str(a["price"])), quantity=Decimal(str(a["quantity"])))
                for a in asks_raw
                if isinstance(a, dict)
            ],
            raw=raw,
        )

    if msg_type == "transaction":
        list_raw = content.get("list") or []
        if not isinstance(list_raw, list) or not list_raw:
            raise SchemaMismatchError("transaction missing list")
        first = list_raw[0]
        sym = _resolve_symbol(first.get("symbol"))
        return TransactionEvent(
            exchange="bithumb",
            symbol=sym,
            event_time=_parse_event_time(first.get("contDtm") or first.get("dateTime") or content.get("timestamp")),
            received_at=received_at,
            price=Decimal(str(first["contPrice"])),
            quantity=Decimal(str(first["contQty"])),
            side="buy" if first.get("buySellGb") in ("1", "buy") else "sell",
            raw=raw,
        )

    raise SchemaMismatchError(f"unknown WS message type: {msg_type!r}")

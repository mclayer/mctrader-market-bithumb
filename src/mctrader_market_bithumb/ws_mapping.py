"""Raw Bithumb WebSocket message dict → typed StreamEvent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


_KST = timezone(timedelta(hours=9))


def _parse_event_time(value: object) -> datetime:
    """Parse Bithumb timestamp formats observed in live envelopes:

    - 16-digit numeric string (microsecond-epoch UTC) — orderbookdepth `content.datetime`
    - 13-digit numeric string (millisecond-epoch UTC) — legacy / ticker `content.timestamp`
    - 10-digit numeric string (second-epoch UTC) — defensive
    - ``"YYYY-MM-DD HH:MM:SS[.ffffff]"`` (KST naive datetime) — transaction `contDtm`
    - ``int`` / ``float`` — treated as ms-epoch (legacy)

    Raises :class:`SchemaMismatchError` for unrecognized formats.
    """
    if isinstance(value, bool):
        # bool is a subclass of int, but it's never a valid timestamp.
        raise SchemaMismatchError(f"invalid event_time: {value!r}")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
    if isinstance(value, str):
        stripped = value.strip()
        # Numeric epoch strings: dispatch by digit count.
        if stripped.isdigit():
            n = int(stripped)
            if len(stripped) >= 16:
                return datetime.fromtimestamp(n / 1_000_000.0, tz=timezone.utc)
            if len(stripped) >= 13:
                return datetime.fromtimestamp(n / 1_000.0, tz=timezone.utc)
            return datetime.fromtimestamp(n, tz=timezone.utc)
        # KST naive datetime string (Bithumb transaction.contDtm).
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                naive = datetime.strptime(stripped, fmt)
            except ValueError:
                continue
            return naive.replace(tzinfo=_KST).astimezone(timezone.utc)
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

    # Bithumb live: `datetime` (lowercase, us-epoch) on orderbookdepth; legacy `dateTime` / `date` / `timestamp`
    ts_raw = (
        content.get("datetime")
        or content.get("dateTime")
        or content.get("date")
        or content.get("timestamp")
    )
    event_time = _parse_event_time(ts_raw) if ts_raw else received_at

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
        # Live Bithumb envelope keeps symbol on each list entry, not on content. Fall back
        # to content.symbol for forward-compat if the envelope ever moves it up.
        changes_raw = content.get("list") or []
        if not isinstance(changes_raw, list) or not changes_raw:
            raise SchemaMismatchError("orderbookdepth list must be non-empty array")
        if symbol is None:
            first = changes_raw[0]
            if not isinstance(first, dict) or first.get("symbol") is None:
                raise SchemaMismatchError("orderbookdepth missing symbol")
            symbol = _resolve_symbol(first["symbol"])
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

"""Subscribe message builder + type allowlist."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from mctrader_market.types import Symbol

from mctrader_market_bithumb.mapping import symbol_to_bithumb_path
from mctrader_market_bithumb.ws_secret_guard import assert_subscribe_payload_safe

Channel = Literal["ticker", "orderbookdepth", "transaction", "orderbooksnapshot"]


def build_subscribe_message(
    *,
    symbol: Symbol,
    channels: Iterable[Channel],
    tick_types: list[str] | None = None,
) -> list[dict[str, object]]:
    """Build per-channel subscribe message list (Bithumb requires one message per type).

    All payloads are validated by :func:`assert_subscribe_payload_safe` before return.
    """
    bithumb_path = symbol_to_bithumb_path(symbol)
    messages: list[dict[str, object]] = []
    for channel in channels:
        payload: dict[str, object] = {
            "type": channel,
            "symbols": [bithumb_path],
        }
        if channel == "ticker" and tick_types:
            payload["tickTypes"] = tick_types
        assert_subscribe_payload_safe(payload)
        messages.append(payload)
    return messages

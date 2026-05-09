"""Subscribe message builder tests."""

from __future__ import annotations

import pytest

from mctrader_market.types import Symbol

from mctrader_market_bithumb.exceptions import PublicOnlyViolationError
from mctrader_market_bithumb.ws_subscribe import build_subscribe_message


def test_build_subscribe_message_basic() -> None:
    msgs = build_subscribe_message(
        symbol=Symbol(base="BTC", quote="KRW"),
        channels=("ticker", "transaction"),
    )
    assert len(msgs) == 2
    assert msgs[0]["type"] == "ticker"
    assert msgs[0]["symbols"] == ["BTC_KRW"]
    assert msgs[1]["type"] == "transaction"


def test_build_subscribe_message_with_tick_types() -> None:
    msgs = build_subscribe_message(
        symbol=Symbol(base="BTC", quote="KRW"),
        channels=("ticker",),
        tick_types=["1H"],
    )
    assert msgs[0]["tickTypes"] == ["1H"]


def test_build_subscribe_message_rejects_private_channel() -> None:
    with pytest.raises(PublicOnlyViolationError):
        build_subscribe_message(
            symbol=Symbol(base="BTC", quote="KRW"),
            channels=("user_orders",),  # type: ignore[arg-type]
        )


# MCT-104 §D14 — orderbooksnapshot channel (wiretap-confirmed 2026-05-09)

def test_build_subscribe_message_orderbooksnapshot() -> None:
    """orderbooksnapshot payload must be {type, symbols} — no tick_types field."""
    msgs = build_subscribe_message(
        symbol=Symbol(base="BTC", quote="KRW"),
        channels=("orderbooksnapshot",),
    )
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg["type"] == "orderbooksnapshot"
    assert msg["symbols"] == ["BTC_KRW"]
    assert "tickTypes" not in msg


def test_build_subscribe_message_multiplex_all_channels() -> None:
    """All 4 channels can be combined in one call."""
    msgs = build_subscribe_message(
        symbol=Symbol(base="ETH", quote="KRW"),
        channels=("transaction", "orderbookdepth", "orderbooksnapshot"),
    )
    assert len(msgs) == 3
    types = [m["type"] for m in msgs]
    assert "transaction" in types
    assert "orderbookdepth" in types
    assert "orderbooksnapshot" in types

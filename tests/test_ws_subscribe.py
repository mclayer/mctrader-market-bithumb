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

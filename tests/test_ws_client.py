"""BithumbWebSocketStream — Protocol satisfaction + URL guard + indefinite reconnect."""

from __future__ import annotations

import pytest

from mctrader_market.types import Symbol

from mctrader_market_bithumb.exceptions import PublicOnlyViolationError
from mctrader_market_bithumb.ws_client import BithumbWebSocketStream, MarketStream


def test_construct_with_canonical_url() -> None:
    stream = BithumbWebSocketStream(symbol=Symbol(base="BTC", quote="KRW"))
    assert isinstance(stream, MarketStream)


def test_construct_rejects_disallowed_url() -> None:
    with pytest.raises(PublicOnlyViolationError):
        BithumbWebSocketStream(
            symbol=Symbol(base="BTC", quote="KRW"),
            url="wss://evil.example.com/ws",
        )


def test_construct_rejects_authorization_header() -> None:
    with pytest.raises(PublicOnlyViolationError):
        BithumbWebSocketStream(
            symbol=Symbol(base="BTC", quote="KRW"),
            extra_headers={"Authorization": "Bearer x"},
        )


def test_backoff_grows_then_caps() -> None:
    stream = BithumbWebSocketStream(
        symbol=Symbol(base="BTC", quote="KRW"),
        backoff_initial_seconds=1.0,
        backoff_max_seconds=8.0,
        backoff_jitter=0.0,
        random_provider=lambda: 0.5,
    )
    assert stream._next_backoff(0) == 1.0
    assert stream._next_backoff(1) == 2.0
    assert stream._next_backoff(2) == 4.0
    assert stream._next_backoff(3) == 8.0
    assert stream._next_backoff(10) == 8.0  # capped

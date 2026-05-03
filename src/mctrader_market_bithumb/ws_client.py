"""BithumbWebSocketStream — Pure async MarketStream impl.

Public-only enforcement (4 layer per MCT-19 A7):
- URL allowlist via :func:`assert_url_allowed`
- handshake header guard via :func:`assert_no_secret_headers`
- subscribe payload guard via :func:`assert_subscribe_payload_safe`
- policy lint = ``tests/test_ws_policy_imports.py`` (forbidden literal scan)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

import websockets

from mctrader_market.types import Symbol

from mctrader_market_bithumb.exceptions import SchemaMismatchError
from mctrader_market_bithumb.ws_events import StreamEvent
from mctrader_market_bithumb.ws_mapping import normalize_message
from mctrader_market_bithumb.ws_secret_guard import (
    ALLOWED_WS_URL,
    assert_no_secret_headers,
    assert_url_allowed,
)
from mctrader_market_bithumb.ws_subscribe import Channel, build_subscribe_message

logger = logging.getLogger(__name__)


@runtime_checkable
class MarketStream(Protocol):
    """Exchange-neutral realtime market data stream."""

    async def __aenter__(self) -> "MarketStream": ...
    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def messages(self) -> AsyncIterator[StreamEvent]: ...


class BithumbWebSocketStream:
    """Pure async Bithumb public WebSocket stream.

    Indefinite reconnect with capped exponential backoff + jitter, server ping/pong
    handled by :mod:`websockets`, stale detection via ``stale_seconds``.
    """

    def __init__(
        self,
        *,
        symbol: Symbol,
        channels: Iterable[Channel] = ("ticker", "transaction"),
        url: str = ALLOWED_WS_URL,
        extra_headers: dict[str, str] | None = None,
        stale_seconds: float = 90.0,
        backoff_initial_seconds: float = 1.0,
        backoff_max_seconds: float = 60.0,
        backoff_jitter: float = 0.2,
        random_provider: callable = random.random,  # type: ignore[type-arg]
    ) -> None:
        assert_url_allowed(url)
        if extra_headers:
            assert_no_secret_headers(extra_headers)

        self._symbol = symbol
        self._channels = tuple(channels)
        self._url = url
        self._extra_headers = extra_headers or {}
        self._stale_seconds = stale_seconds
        self._backoff_initial = backoff_initial_seconds
        self._backoff_max = backoff_max_seconds
        self._jitter = backoff_jitter
        self._random = random_provider

        self._connection: Any | None = None
        self._closed = False

    async def __aenter__(self) -> "BithumbWebSocketStream":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def close(self) -> None:
        self._closed = True
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:  # pragma: no cover - best effort
                pass
            self._connection = None

    async def messages(self) -> AsyncIterator[StreamEvent]:
        attempt = 0
        while not self._closed:
            try:
                async with websockets.connect(self._url, extra_headers=self._extra_headers or None) as ws:
                    self._connection = ws
                    attempt = 0
                    await self._send_subscriptions(ws)
                    async for raw_text in self._iter_with_stale_guard(ws):
                        try:
                            payload = json.loads(raw_text)
                        except json.JSONDecodeError as exc:
                            raise SchemaMismatchError(f"WS payload not JSON: {exc}") from exc
                        event = normalize_message(payload, received_at=datetime.now(timezone.utc))
                        if event is not None:
                            yield event
            except (websockets.ConnectionClosed, asyncio.TimeoutError, OSError) as exc:
                if self._closed:
                    return
                delay = self._next_backoff(attempt)
                logger.warning("WS reconnect in %.2fs (attempt=%d, reason=%s)", delay, attempt, exc)
                await asyncio.sleep(delay)
                attempt += 1
            except SchemaMismatchError:
                raise

    async def _send_subscriptions(self, ws: Any) -> None:
        for message in build_subscribe_message(symbol=self._symbol, channels=self._channels):
            await ws.send(json.dumps(message))

    async def _iter_with_stale_guard(self, ws: Any) -> AsyncIterator[str]:
        while True:
            try:
                raw_text = await asyncio.wait_for(ws.recv(), timeout=self._stale_seconds)
            except asyncio.TimeoutError:
                logger.warning("WS stale (%.0fs without message), forcing reconnect", self._stale_seconds)
                await ws.close()
                return
            yield raw_text

    def _next_backoff(self, attempt: int) -> float:
        base = min(self._backoff_initial * (2**attempt), self._backoff_max)
        jitter_pct = (self._random() * 2 - 1) * self._jitter
        return max(0.0, base * (1.0 + jitter_pct))


@asynccontextmanager
async def open_stream(
    *,
    symbol: Symbol,
    channels: Iterable[Channel] = ("ticker", "transaction"),
) -> AsyncIterator[BithumbWebSocketStream]:
    stream = BithumbWebSocketStream(symbol=symbol, channels=channels)
    async with stream:
        yield stream

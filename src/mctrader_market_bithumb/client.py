"""Bithumb HTTP client — public OHLCV endpoint with rate limit + retry classification."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from mctrader_market_bithumb.exceptions import (
    BithumbApiError,
    PublicOnlyViolationError,
    RateLimitedError,
    SchemaMismatchError,
)

BASE_URL = "https://api.bithumb.com/public"

FORBIDDEN_HEADERS: frozenset[str] = frozenset(
    {
        "Authorization",
        "Api-Key",
        "Api-Sign",
        "X-Api-Key",
        "X-BITHUMB-Api-Key",
        "X-BITHUMB-Api-Sign",
        "X-BITHUMB-Api-Nonce",
    }
)

FORBIDDEN_HEADER_NAMES_LOWER: frozenset[str] = frozenset(h.lower() for h in FORBIDDEN_HEADERS)


@dataclass
class RateLimitConfig:
    rate_per_second: float = 30.0  # 33% of Bithumb public 90/sec
    burst: int = 30


@dataclass
class RetryConfig:
    max_attempts: int = 3
    backoff_base_seconds: float = 0.25  # 0.25, 0.5, 1.0
    jitter_factor: float = 0.2


class _TokenBucket:
    """Process-local global token bucket (single-process semantics)."""

    def __init__(
        self,
        rate_per_second: float,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate = rate_per_second
        self._capacity = burst
        self._tokens = float(burst)
        self._last = clock()
        self._lock = threading.Lock()
        self._clock = clock

    def acquire(self, sleep: Callable[[float], None] = time.sleep) -> None:
        with self._lock:
            now = self._clock()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self._rate
        sleep(wait)
        # After sleep, recurse without holding lock; refill happens on next call.
        return self.acquire(sleep=sleep)


def _assert_no_secret_headers(headers: dict[str, str]) -> None:
    forbidden_present = {h for h in headers if h.lower() in FORBIDDEN_HEADER_NAMES_LOWER}
    if forbidden_present:
        raise PublicOnlyViolationError(
            f"forbidden header present: {sorted(forbidden_present)} (ADR-008 D5)"
        )


class BithumbHttpClient:
    """Public-only Bithumb HTTP client.

    The base URL is fixed to ``https://api.bithumb.com/public`` and only the candlestick path
    is exposed via :py:meth:`get_candlestick`.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        rate_limit: RateLimitConfig | None = None,
        retry: RetryConfig | None = None,
        timeout: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        random_provider: Callable[[], float] | None = None,
    ) -> None:
        self._owned_client = client is None
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._rate_limit = rate_limit or RateLimitConfig()
        self._retry = retry or RetryConfig()
        self._bucket = _TokenBucket(self._rate_limit.rate_per_second, self._rate_limit.burst, clock)
        self._sleep = sleep
        self._random = random_provider

    def close(self) -> None:
        if self._owned_client:
            self._client.close()

    def __enter__(self) -> BithumbHttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_candlestick(self, symbol_path: str, chart_interval: str) -> Any:
        """Fetch raw response body for ``/candlestick/{symbol_path}/{chart_interval}``."""
        path = f"/candlestick/{symbol_path}/{chart_interval}"
        return self._request_with_retry("GET", path)

    def get_orderbook(self, symbol_path: str) -> Any:
        """Fetch raw response body for ``/orderbook/{symbol_path}``.

        Returns the full orderbook snapshot including ``bids`` and ``asks`` arrays.
        Each entry is ``{"price": str, "quantity": str}``.
        """
        path = f"/orderbook/{symbol_path}"
        return self._request_with_retry("GET", path)

    def get_ticker_all_krw(self) -> Any:
        """Fetch raw response body for ``/ticker/ALL_KRW``.

        Returns the full ticker snapshot for all KRW pairs including ``acc_trade_value_24H``
        and ``acc_trade_price_24H``. Used as the primary source for :meth:`fetch_assetsstatus_all`.
        """
        return self._request_with_retry("GET", "/ticker/ALL_KRW")

    def fetch_assetsstatus_all(self) -> dict[str, str]:
        """Fetch asset deposit/withdrawal status for all currencies.

        Calls ``GET /assetsstatus/multichain/ALL`` and returns a mapping of
        ``currency_code -> asset_status`` where ``asset_status`` is one of
        ``"1"`` (normal) or ``"0"`` (suspended/maintenance).

        Raises :class:`SchemaMismatchError` when the response schema is unexpected.
        Raises :class:`BithumbApiError` on HTTP failure or non-"0000" status code.
        """
        raw = self._request_with_retry("GET", "/assetsstatus/multichain/ALL")
        if not isinstance(raw, dict):
            raise SchemaMismatchError(f"assetsstatus: expected dict response, got {type(raw).__name__}")
        status_code = raw.get("status")
        if status_code != "0000":
            raise BithumbApiError(
                f"assetsstatus API returned non-0000 status: {status_code!r} "
                f"message={raw.get('message', '')!r}"
            )
        data = raw.get("data")
        if not isinstance(data, list):
            raise SchemaMismatchError(
                f"assetsstatus: expected data=list, got {type(data).__name__}"
            )
        result: dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            currency = item.get("currency")
            # depositStatus + withdrawalStatus: "1" = active, "0" = suspended.
            # We expose the more restrictive (min) of the two as a single asset_status.
            deposit = str(item.get("depositStatus", "0"))
            withdrawal = str(item.get("withdrawalStatus", "0"))
            combined = "1" if deposit == "1" and withdrawal == "1" else "0"
            if isinstance(currency, str) and currency:
                result[currency] = combined
        return result

    def _request_with_retry(self, method: str, path: str) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._retry.max_attempts):
            self._bucket.acquire(self._sleep)
            try:
                response = self._send(method, path)
                self._classify(response)
                return response.json()
            except (httpx.TransportError, _Transient5xx) as exc:
                last_exc = exc
                if attempt + 1 >= self._retry.max_attempts:
                    raise BithumbApiError(f"transient failure after {attempt + 1} attempts: {exc}") from exc
                self._sleep(self._next_backoff(attempt))
            except (RateLimitedError, BithumbApiError, SchemaMismatchError):
                raise
        # unreachable
        raise BithumbApiError(f"unexpected retry exit: {last_exc}")  # pragma: no cover

    def _send(self, method: str, path: str) -> httpx.Response:
        # base_url 가 client 레벨에 set 되어 있다고 가정. 임의 URL 차단 위해 path 만 받는다.
        request = self._client.build_request(method, path)
        _assert_no_secret_headers(dict(request.headers))
        return self._client.send(request)

    def _classify(self, response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            try:
                response.json()
            except ValueError as exc:
                raise SchemaMismatchError(f"response not JSON: {exc}") from exc
            return
        if status == 429:
            raise RateLimitedError(f"rate limited (HTTP 429): {response.text[:200]}")
        if 400 <= status < 500:
            raise BithumbApiError(f"client error HTTP {status}: {response.text[:200]}")
        if 500 <= status < 600:
            raise _Transient5xx(f"transient HTTP {status}")
        raise BithumbApiError(f"unexpected HTTP {status}")

    def _next_backoff(self, attempt: int) -> float:
        base = self._retry.backoff_base_seconds * (2**attempt)
        if self._random is None:
            return base
        jitter = (self._random() * 2 - 1) * self._retry.jitter_factor * base
        return max(0.0, base + jitter)


class _Transient5xx(Exception):
    """Internal marker for retryable 5xx — never escapes adapter layer."""

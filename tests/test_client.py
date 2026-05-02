"""BithumbHttpClient tests — retry classification + secret guard + rate limit."""

from __future__ import annotations

import httpx
import pytest

from mctrader_market_bithumb.client import (
    FORBIDDEN_HEADERS,
    BithumbHttpClient,
    RateLimitConfig,
    RetryConfig,
    _assert_no_secret_headers,
    _TokenBucket,
)
from mctrader_market_bithumb.exceptions import (
    BithumbApiError,
    PublicOnlyViolationError,
    RateLimitedError,
    SchemaMismatchError,
)


def _client_with_handler(handler) -> BithumbHttpClient:
    transport = httpx.MockTransport(handler)
    return BithumbHttpClient(
        client=httpx.Client(base_url="https://api.bithumb.com/public", transport=transport),
        rate_limit=RateLimitConfig(rate_per_second=1000, burst=100),  # disable in tests
        retry=RetryConfig(max_attempts=3, backoff_base_seconds=0.0),
        sleep=lambda _: None,
    )


def test_secret_guard_rejects_authorization_header() -> None:
    with pytest.raises(PublicOnlyViolationError):
        _assert_no_secret_headers({"Authorization": "Bearer x"})


def test_secret_guard_rejects_api_key_header() -> None:
    with pytest.raises(PublicOnlyViolationError):
        _assert_no_secret_headers({"Api-Key": "x"})


def test_secret_guard_allows_normal_headers() -> None:
    _assert_no_secret_headers({"User-Agent": "test", "Accept": "application/json"})


def test_forbidden_headers_set_includes_bithumb_signing() -> None:
    assert "X-BITHUMB-Api-Key" in FORBIDDEN_HEADERS
    assert "X-BITHUMB-Api-Sign" in FORBIDDEN_HEADERS


def test_get_candlestick_returns_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/candlestick/BTC_KRW/1h" in request.url.path
        return httpx.Response(200, json={"status": "0000", "data": []})

    client = _client_with_handler(handler)
    payload = client.get_candlestick("BTC_KRW", "1h")
    assert payload == {"status": "0000", "data": []}


def test_5xx_retries_until_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"status": "0000", "data": []})

    client = _client_with_handler(handler)
    payload = client.get_candlestick("BTC_KRW", "1h")
    assert payload == {"status": "0000", "data": []}
    assert calls["n"] == 2


def test_5xx_exhausts_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = _client_with_handler(handler)
    with pytest.raises(BithumbApiError, match="transient"):
        client.get_candlestick("BTC_KRW", "1h")


def test_429_rate_limited_no_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429)

    client = _client_with_handler(handler)
    with pytest.raises(RateLimitedError):
        client.get_candlestick("BTC_KRW", "1h")
    assert calls["n"] == 1


def test_4xx_classified_no_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = _client_with_handler(handler)
    with pytest.raises(BithumbApiError):
        client.get_candlestick("BTC_KRW", "1h")


def test_invalid_json_raises_schema_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    client = _client_with_handler(handler)
    with pytest.raises(SchemaMismatchError):
        client.get_candlestick("BTC_KRW", "1h")


class TestTokenBucket:
    def test_initial_tokens_match_burst(self) -> None:
        clock_value = {"t": 0.0}
        bucket = _TokenBucket(rate_per_second=10.0, burst=3, clock=lambda: clock_value["t"])
        sleeps: list[float] = []
        # Burst capacity = 3 requests immediately
        for _ in range(3):
            bucket.acquire(sleep=lambda d: sleeps.append(d))
        assert sleeps == []

    def test_refill_after_time(self) -> None:
        clock_value = {"t": 0.0}
        bucket = _TokenBucket(rate_per_second=10.0, burst=2, clock=lambda: clock_value["t"])
        # Consume burst
        bucket.acquire(sleep=lambda _: None)
        bucket.acquire(sleep=lambda _: None)
        # Advance time = +1.0s → 10 new tokens, capped at burst=2
        clock_value["t"] = 1.0
        bucket.acquire(sleep=lambda _: None)  # should not sleep

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


# MCT-104 — fetch_assetsstatus_all (§D13 metadata source, 2026-05-09)

def test_fetch_assetsstatus_all_normal() -> None:
    """Both deposit+withdrawal active → combined status '1'."""
    payload = {
        "status": "0000",
        "data": [
            {"currency": "BTC", "depositStatus": 1, "withdrawalStatus": 1},
            {"currency": "ETH", "depositStatus": 1, "withdrawalStatus": 0},
            {"currency": "XRP", "depositStatus": 0, "withdrawalStatus": 0},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/assetsstatus/multichain/ALL" in request.url.path
        return httpx.Response(200, json=payload)

    client = _client_with_handler(handler)
    result = client.fetch_assetsstatus_all()
    assert result["BTC"] == "1"   # both active
    assert result["ETH"] == "0"   # withdrawal suspended
    assert result["XRP"] == "0"   # both suspended


def test_fetch_assetsstatus_all_non_0000_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "5100", "message": "Bad Request"})

    client = _client_with_handler(handler)
    with pytest.raises(BithumbApiError, match="non-0000"):
        client.fetch_assetsstatus_all()


def test_fetch_assetsstatus_all_bad_schema_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "0000", "data": "unexpected_string"})

    client = _client_with_handler(handler)
    with pytest.raises(SchemaMismatchError):
        client.fetch_assetsstatus_all()


def test_get_ticker_all_krw_returns_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/ticker/ALL_KRW" in request.url.path
        return httpx.Response(200, json={"status": "0000", "data": {"date": "1234567890123"}})

    client = _client_with_handler(handler)
    result = client.get_ticker_all_krw()
    assert result["status"] == "0000"


def test_read_error_retries_and_raises_bithumb_api_error() -> None:
    """httpx.ReadError (a TransportError subclass) must trigger retry logic and ultimately raise BithumbApiError."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadError("connection reset", request=request)

    transport = httpx.MockTransport(handler)
    client = BithumbHttpClient(
        client=httpx.Client(base_url="https://api.bithumb.com/public", transport=transport),
        rate_limit=RateLimitConfig(rate_per_second=1000, burst=100),
        retry=RetryConfig(max_attempts=3, backoff_base_seconds=0.0),
        sleep=lambda _: None,
    )
    with pytest.raises(BithumbApiError, match="transient"):
        client.get_candlestick("BTC_KRW", "1h")
    # All 3 attempts must have been made before giving up
    assert calls["n"] == 3


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

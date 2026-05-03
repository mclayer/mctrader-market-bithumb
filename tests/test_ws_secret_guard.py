"""WebSocket public-only enforcement (4 layer) tests."""

from __future__ import annotations

import pytest

from mctrader_market_bithumb.exceptions import PublicOnlyViolationError
from mctrader_market_bithumb.ws_secret_guard import (
    ALLOWED_SUBSCRIBE_TYPES,
    ALLOWED_WS_URL,
    FORBIDDEN_HEADERS,
    assert_no_secret_headers,
    assert_subscribe_payload_safe,
    assert_url_allowed,
)


def test_url_allowlist_accepts_canonical() -> None:
    assert_url_allowed(ALLOWED_WS_URL)


def test_url_allowlist_rejects_other_host() -> None:
    with pytest.raises(PublicOnlyViolationError):
        assert_url_allowed("wss://evil.example.com/pub/ws")


def test_url_allowlist_rejects_private_path() -> None:
    with pytest.raises(PublicOnlyViolationError):
        assert_url_allowed("wss://pubwss.bithumb.com/private/ws")


def test_handshake_header_guard_rejects_authorization() -> None:
    with pytest.raises(PublicOnlyViolationError):
        assert_no_secret_headers({"Authorization": "Bearer x"})


def test_handshake_header_guard_rejects_bithumb_signing() -> None:
    with pytest.raises(PublicOnlyViolationError):
        assert_no_secret_headers({"X-BITHUMB-Api-Key": "x"})


def test_handshake_header_guard_allows_normal() -> None:
    assert_no_secret_headers({"User-Agent": "test", "Accept": "application/json"})


def test_subscribe_type_allowlist_only() -> None:
    for sub_type in ALLOWED_SUBSCRIBE_TYPES:
        assert_subscribe_payload_safe({"type": sub_type, "symbols": ["BTC_KRW"]})


def test_subscribe_rejects_private_account_type() -> None:
    with pytest.raises(PublicOnlyViolationError, match="not in allowlist"):
        assert_subscribe_payload_safe({"type": "private_account", "symbols": ["BTC_KRW"]})


def test_subscribe_rejects_authorization_payload_key() -> None:
    with pytest.raises(PublicOnlyViolationError, match="forbidden subscribe payload key"):
        assert_subscribe_payload_safe({
            "type": "ticker",
            "symbols": ["BTC_KRW"],
            "Authorization": "x",
        })


def test_forbidden_headers_includes_bithumb() -> None:
    assert "X-BITHUMB-Api-Sign" in FORBIDDEN_HEADERS
    assert "Api-Key" in FORBIDDEN_HEADERS

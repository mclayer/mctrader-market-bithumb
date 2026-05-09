"""4-layer public-only enforcement extension for WebSocket (MCT-19 A7)."""

from __future__ import annotations

from typing import Any

from mctrader_market_bithumb.exceptions import PublicOnlyViolationError

ALLOWED_WS_URL = "wss://pubwss.bithumb.com/pub/ws"

FORBIDDEN_HEADERS: frozenset[str] = frozenset(
    {
        "Authorization",
        "Api-Key",
        "Api-Sign",
        "X-BITHUMB-Api-Key",
        "X-BITHUMB-Api-Sign",
        "X-BITHUMB-Api-Nonce",
    }
)

ALLOWED_SUBSCRIBE_TYPES: frozenset[str] = frozenset(
    {"ticker", "orderbookdepth", "transaction", "orderbooksnapshot"}
)

FORBIDDEN_SUBSCRIBE_KEYS: frozenset[str] = frozenset(
    {"Authorization", "apiKey", "api-key", "secret", "signature", "nonce"}
)


def assert_url_allowed(url: str) -> None:
    if url != ALLOWED_WS_URL:
        raise PublicOnlyViolationError(
            f"WebSocket URL not in allowlist: {url} (allowed: {ALLOWED_WS_URL})"
        )


def assert_no_secret_headers(headers: dict[str, str]) -> None:
    _forbidden_lower = {h.lower() for h in FORBIDDEN_HEADERS}
    forbidden = {h for h in headers if h.lower() in _forbidden_lower}
    if forbidden:
        raise PublicOnlyViolationError(
            f"forbidden WS handshake header: {sorted(forbidden)} (ADR-008 D5)"
        )


def assert_subscribe_payload_safe(payload: dict[str, Any]) -> None:
    sub_type = payload.get("type")
    if sub_type not in ALLOWED_SUBSCRIBE_TYPES:
        raise PublicOnlyViolationError(
            f"subscribe type {sub_type!r} not in allowlist {sorted(ALLOWED_SUBSCRIBE_TYPES)}"
        )
    _forbidden_lower = {k.lower() for k in FORBIDDEN_SUBSCRIBE_KEYS}
    forbidden = {k for k in payload if k.lower() in _forbidden_lower}
    if forbidden:
        raise PublicOnlyViolationError(
            f"forbidden subscribe payload key: {sorted(forbidden)}"
        )

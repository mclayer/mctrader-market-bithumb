"""WS policy lint extension — extra forbidden patterns for WebSocket auth."""

from __future__ import annotations

from pathlib import Path

SRC_ROOT = Path(__file__).parent.parent / "src" / "mctrader_market_bithumb"

# Source must NOT call websockets.connect with extra_headers carrying auth, nor pass
# Authorization-bearing headers via aiohttp / httpx-ws.
FORBIDDEN_WS_AUTH_PATTERNS = (
    "extra_headers={\"Authorization",
    "extra_headers={'Authorization",
    "extra_headers=[(\"Authorization",
    "extra_headers=[('Authorization",
    "Authorization\": \"Bearer",
    "Api-Sign\": ",
    "1password",
    "from onepassword",
)


def test_ws_source_has_no_forbidden_auth_patterns() -> None:
    violations: list[str] = []
    for source_file in SRC_ROOT.rglob("*.py"):
        text = source_file.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_WS_AUTH_PATTERNS:
            if pattern in text:
                violations.append(f"{source_file.relative_to(SRC_ROOT)}: forbidden ws-auth pattern {pattern!r}")
    assert not violations, "\n".join(violations)


def test_no_aiohttp_ws_auth_kwarg_in_source() -> None:
    """aiohttp.ClientSession.ws_connect(auth=...) usage must be absent."""
    violations: list[str] = []
    for source_file in SRC_ROOT.rglob("*.py"):
        text = source_file.read_text(encoding="utf-8")
        if ".ws_connect(" in text and "auth=" in text:
            violations.append(f"{source_file.relative_to(SRC_ROOT)}: aiohttp ws_connect(auth=...)")
    assert not violations, "\n".join(violations)

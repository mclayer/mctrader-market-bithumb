"""Typed exceptions for adapter ↔ storage boundary."""

from __future__ import annotations


class BithumbApiError(Exception):
    """Base for Bithumb HTTP API failures classified by adapter (no auto retry)."""


class RateLimitedError(BithumbApiError):
    """HTTP 429 — storage policy decides next action (no auto retry)."""


class SchemaMismatchError(BithumbApiError):
    """200 + JSON parse / row length / type error — no retry."""


class InsufficientCoverageError(BithumbApiError):
    """Response window does not cover ``[start, end)`` requested interval."""


class PublicOnlyViolationError(BithumbApiError):
    """Forbidden header / non-public URL detected (ADR-008 D5)."""

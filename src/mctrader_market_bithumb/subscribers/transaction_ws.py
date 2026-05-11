"""Bithumb transaction WS → tick.v1.1 emitter (MCT-138, Epic MCT-112 Story-4).

Pipeline:
    raw WS frame bytes ─► JSON parse ─► validation
                                          │
                                          ├─ ok    ─► TickRowV1_1(validation_status=OK,
                                          │              ingest_seq, payload_hash)
                                          │
                                          └─ bad   ─► QuarantineRecord(reason, raw_bytes,
                                                       payload_hash, received_at)

Reconnect handling:
- The owning WS client calls :meth:`TransactionTickEmitter.mark_reconnect_boundary`
  on `(re)connect`; the very next emitted row is tagged with
  ``validation_status=RECONNECT_BOUNDARY``, and the internal :class:`GapDetector`
  state is cleared.

ADR-009 §D12.2 (CRITICAL): Bithumb public API does NOT provide ticks historical
replay. Quarantine rows + GAP-tagged windows are evidence-only — downstream
consumers must exclude them from strategy input (no backfill possible).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from mctrader_market.schemas import TickRowV1_1
from mctrader_market.types import Symbol

from mctrader_market_bithumb.exceptions import SchemaMismatchError
from mctrader_market_bithumb.subscribers.gap_detector import GapDetector
from mctrader_market_bithumb.subscribers.ingest_seq_counter import IngestSeqCounter
from mctrader_market_bithumb.ws_mapping import _parse_event_time, _resolve_symbol

logger = logging.getLogger(__name__)


QuarantineReason = Literal["INVALID_JSON", "SCHEMA_MISMATCH", "INVALID_VALUE", "UNKNOWN_SIDE"]


class MalformedPayloadError(Exception):
    """Internal sentinel for the validation pipeline.

    Captures the quarantine reason so the orchestrator (`TransactionTickEmitter.process`)
    can route the raw bytes into :class:`QuarantineRecord`. Not part of the public API.
    """

    def __init__(self, reason: QuarantineReason, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason: QuarantineReason = reason
        self.detail = detail


@dataclass(frozen=True)
class QuarantineRecord:
    """Evidence row for a malformed transaction frame (ADR-009 §D12.2)."""

    received_at: datetime
    raw_bytes: bytes
    payload_hash: str
    reason: QuarantineReason
    detail: str = ""


# ── helpers ──────────────────────────────────────────────────────────────


def compute_payload_hash(raw_bytes: bytes) -> str:
    """Return the first 16 hex chars of sha256(raw_bytes) — payload_hash column."""
    return hashlib.sha256(raw_bytes).hexdigest()[:16]


def _to_decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MalformedPayloadError(
            "INVALID_VALUE", f"{field_name} not Decimal-coercible: {value!r}"
        ) from exc


_BUY_TOKENS = frozenset({"1", "buy", "BUY"})
_SELL_TOKENS = frozenset({"2", "sell", "SELL"})


def _normalize_side(raw_side: Any) -> Literal["BUY", "SELL"]:
    if raw_side in _BUY_TOKENS:
        return "BUY"
    if raw_side in _SELL_TOKENS:
        return "SELL"
    raise MalformedPayloadError(
        "UNKNOWN_SIDE", f"buySellGb not in {{1,buy,2,sell}}: {raw_side!r}"
    )


def _make_trade_id(*, symbol: Symbol, ts_utc: datetime, idx: int) -> str:
    """Deterministic synthetic trade_id (Bithumb WS frames omit a stable id).

    Format: ``"{base}_{quote}-{us_epoch}-{idx}"`` — stable across re-emissions of
    identical bytes, sufficient as a tuple component for downstream WAL dedup
    ``(exchange, symbol, ts_utc, trade_id, payload_hash)``.
    """
    us_epoch = int(ts_utc.timestamp() * 1_000_000)
    return f"{symbol.base}_{symbol.quote}-{us_epoch}-{idx}"


# ── stateless single-frame conversion ────────────────────────────────────


def build_transaction_tick_row(
    *,
    raw_bytes: bytes,
    received_at: datetime,
    ingest_seq_counter: IngestSeqCounter,
    validation_status_override: Literal["OK", "RECONNECT_BOUNDARY", "GAP"] | None = None,
) -> list[TickRowV1_1]:
    """Convert one Bithumb transaction WS frame to ``list[TickRowV1_1]``.

    A single frame can contain multiple list entries (per Bithumb envelope) —
    each emits one row with its own ingest_seq and trade_id, sharing the
    same payload_hash (the hash of the whole frame, by contract).

    Raises :class:`MalformedPayloadError` on any validation failure — the caller
    is responsible for routing the raw bytes to quarantine.
    """
    payload_hash = compute_payload_hash(raw_bytes)
    try:
        payload = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise MalformedPayloadError("INVALID_JSON", str(exc)) from exc

    if not isinstance(payload, dict):
        raise MalformedPayloadError("SCHEMA_MISMATCH", "top-level not dict")
    if payload.get("type") != "transaction":
        raise MalformedPayloadError(
            "SCHEMA_MISMATCH",
            f"type must be 'transaction', got {payload.get('type')!r}",
        )

    content = payload.get("content")
    if not isinstance(content, dict):
        raise MalformedPayloadError("SCHEMA_MISMATCH", "missing content dict")

    list_raw = content.get("list")
    if not isinstance(list_raw, list) or not list_raw:
        raise MalformedPayloadError("SCHEMA_MISMATCH", "content.list must be non-empty array")

    rows: list[TickRowV1_1] = []
    status = validation_status_override or "OK"
    for idx, entry in enumerate(list_raw):
        if not isinstance(entry, dict):
            raise MalformedPayloadError(
                "SCHEMA_MISMATCH", f"list[{idx}] not dict"
            )
        # symbol
        try:
            sym = _resolve_symbol(entry.get("symbol"))
        except SchemaMismatchError as exc:
            raise MalformedPayloadError("SCHEMA_MISMATCH", str(exc)) from exc

        # event_time — accept contDtm (KST) or fallback ms-epoch
        ts_raw = entry.get("contDtm") or entry.get("dateTime") or content.get("timestamp")
        if ts_raw is None:
            raise MalformedPayloadError(
                "SCHEMA_MISMATCH", f"list[{idx}] missing contDtm/dateTime"
            )
        try:
            ts_utc = _parse_event_time(ts_raw)
        except SchemaMismatchError as exc:
            raise MalformedPayloadError("SCHEMA_MISMATCH", str(exc)) from exc

        # price / qty — required, must coerce
        price_raw = entry.get("contPrice")
        qty_raw = entry.get("contQty")
        if price_raw is None:
            raise MalformedPayloadError("SCHEMA_MISMATCH", f"list[{idx}] missing contPrice")
        if qty_raw is None:
            raise MalformedPayloadError("SCHEMA_MISMATCH", f"list[{idx}] missing contQty")
        price = _to_decimal(price_raw, "contPrice")
        qty = _to_decimal(qty_raw, "contQty")
        # Schema-level constraint: price must be > 0, qty >= 0 (tick.v1.1 field_validator).
        # Pre-check here so we can route to MalformedPayloadError (quarantine) instead
        # of letting Pydantic raise ValidationError.
        if price <= 0:
            raise MalformedPayloadError("INVALID_VALUE", f"contPrice <= 0: {price}")
        if qty < 0:
            raise MalformedPayloadError("INVALID_VALUE", f"contQty < 0: {qty}")

        # side
        side = _normalize_side(entry.get("buySellGb"))

        trade_id = _make_trade_id(symbol=sym, ts_utc=ts_utc, idx=idx)
        ingest_seq = ingest_seq_counter.next()
        try:
            row = TickRowV1_1(
                ts_utc=ts_utc,
                exchange="bithumb",
                symbol=sym,
                trade_id=trade_id,
                price=price,
                quantity=qty,
                side=side,
                is_taker=True,  # Bithumb public WS = taker-only feed.
                ingest_seq=ingest_seq,
                payload_hash=payload_hash,
                validation_status=status,
            )
        except Exception as exc:  # pragma: no cover - Pydantic ValidationError fallback
            raise MalformedPayloadError("INVALID_VALUE", str(exc)) from exc
        rows.append(row)
    return rows


# ── stateful facade (counter + gap + reconnect + quarantine) ─────────────


@dataclass
class TransactionTickEmitter:
    """End-to-end facade: raw bytes → ``list[TickRowV1_1]`` + side-channel evidence.

    State:
    - ``_counter`` — per-instance ingest_seq counter (reset on instantiation).
    - ``_gap_detector`` — per-symbol gap state.
    - ``_pending_reconnect`` — flag: next emit is tagged ``RECONNECT_BOUNDARY``.
    - ``_quarantine`` — buffer of :class:`QuarantineRecord`, drained by
      ``drain_quarantine()``.

    Restart semantics: a fresh process → fresh emitter → counter starts at 0
    (Story-6 WAL dedup uses ``(exchange, symbol, ts_utc, trade_id, payload_hash)``
    so ingest_seq reset is safe).
    """

    _counter: IngestSeqCounter = field(default_factory=IngestSeqCounter)
    _gap_detector: GapDetector = field(default_factory=GapDetector)
    _pending_reconnect: bool = False
    _quarantine: list[QuarantineRecord] = field(default_factory=list)

    def mark_reconnect_boundary(self) -> None:
        """Tag the next emitted row as ``RECONNECT_BOUNDARY`` and clear gap state."""
        self._pending_reconnect = True

    def process(self, *, raw_bytes: bytes, received_at: datetime) -> list[TickRowV1_1]:
        """Process one raw WS frame. Returns emitted rows, [] for non-transaction / malformed."""
        # Fast-path: identify message type WITHOUT raising for non-transaction frames.
        try:
            head = json.loads(raw_bytes)
        except json.JSONDecodeError as exc:
            self._quarantine.append(
                QuarantineRecord(
                    received_at=received_at,
                    raw_bytes=raw_bytes,
                    payload_hash=compute_payload_hash(raw_bytes),
                    reason="INVALID_JSON",
                    detail=str(exc),
                )
            )
            return []

        if not isinstance(head, dict):
            self._quarantine.append(
                QuarantineRecord(
                    received_at=received_at,
                    raw_bytes=raw_bytes,
                    payload_hash=compute_payload_hash(raw_bytes),
                    reason="SCHEMA_MISMATCH",
                    detail="top-level not dict",
                )
            )
            return []

        msg_type = head.get("type")
        if msg_type is None:
            # subscribe ack / status — skip silently (mirror ws_mapping.normalize_message).
            return []
        if msg_type != "transaction":
            # Known non-transaction types (ticker / orderbookdepth / orderbooksnapshot) — skip.
            return []

        # Determine the override for this frame BEFORE consuming the counter.
        # RECONNECT_BOUNDARY is one-shot — clear the flag once we attempt to emit.
        override: Literal["OK", "RECONNECT_BOUNDARY", "GAP"] | None = None
        if self._pending_reconnect:
            override = "RECONNECT_BOUNDARY"

        try:
            rows = build_transaction_tick_row(
                raw_bytes=raw_bytes,
                received_at=received_at,
                ingest_seq_counter=self._counter,
                validation_status_override=override,
            )
        except MalformedPayloadError as exc:
            # NOTE: counter is not advanced for malformed frames because
            # build_transaction_tick_row raises BEFORE calling counter.next()
            # on the failing entry. (Validations are performed before the
            # counter is consumed for each entry.)
            self._quarantine.append(
                QuarantineRecord(
                    received_at=received_at,
                    raw_bytes=raw_bytes,
                    payload_hash=compute_payload_hash(raw_bytes),
                    reason=exc.reason,
                    detail=exc.detail,
                )
            )
            return []

        # Successful emit → consume reconnect flag + run gap detection.
        if self._pending_reconnect:
            self._gap_detector.mark_reconnect(at=received_at)
            self._pending_reconnect = False

        # Gap detection (override row.validation_status if a gap is observed AND
        # we didn't already tag RECONNECT_BOUNDARY).
        if override is None:
            updated: list[TickRowV1_1] = []
            for row in rows:
                gap = self._gap_detector.observe(symbol=row.symbol, event_time=row.ts_utc)
                if gap is not None:
                    updated.append(row.model_copy(update={"validation_status": "GAP"}))
                else:
                    updated.append(row)
            return updated
        return rows

    def drain_quarantine(self) -> list[QuarantineRecord]:
        """Return + clear the quarantine buffer."""
        out = list(self._quarantine)
        self._quarantine.clear()
        return out

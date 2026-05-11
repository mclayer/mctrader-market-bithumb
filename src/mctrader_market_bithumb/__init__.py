"""mctrader-market-bithumb — Bithumb public OHLCV REST + WebSocket adapter."""

from mctrader_market_bithumb.adapter import BithumbCandleProvider
from mctrader_market_bithumb.client import BithumbHttpClient, RateLimitConfig, RetryConfig
from mctrader_market_bithumb.rest_throttle import RestThrottle
from mctrader_market_bithumb.exceptions import (
    BithumbApiError,
    InsufficientCoverageError,
    PublicOnlyViolationError,
    RateLimitedError,
    SchemaMismatchError,
)
from mctrader_market_bithumb.mapping import (
    IDX_CLOSE,
    IDX_HIGH,
    IDX_LOW,
    IDX_OPEN,
    IDX_TS_MS,
    IDX_VOLUME,
    ROW_LENGTH,
    bithumb_path_to_symbol,
    normalize_row,
    symbol_to_bithumb_path,
)
from mctrader_market_bithumb.ws_client import BithumbWebSocketStream, MarketStream
from mctrader_market_bithumb.ws_events import (
    OrderbookDeltaEvent,
    OrderbookSnapshotEvent,
    StreamEvent,
    TickerEvent,
    TransactionEvent,
)
from mctrader_market_bithumb.ws_mapping import normalize_message
# MCT-138 — tick.v1.1 emitter + gap detection (Epic MCT-112 Story-4).
from mctrader_market_bithumb.subscribers import (
    GAP_THRESHOLD_SECONDS_DEFAULT,
    GapDetector,
    GapEvent,
    IngestSeqCounter,
    QuarantineRecord,
    TransactionTickEmitter,
    build_transaction_tick_row,
    compute_payload_hash,
)

__version__ = "0.4.0"

__all__ = [
    "BithumbApiError",
    "BithumbCandleProvider",
    "BithumbHttpClient",
    "BithumbWebSocketStream",
    "GAP_THRESHOLD_SECONDS_DEFAULT",
    "GapDetector",
    "GapEvent",
    "IDX_CLOSE",
    "IDX_HIGH",
    "IDX_LOW",
    "IDX_OPEN",
    "IDX_TS_MS",
    "IDX_VOLUME",
    "IngestSeqCounter",
    "InsufficientCoverageError",
    "MarketStream",
    "OrderbookDeltaEvent",
    "OrderbookSnapshotEvent",
    "PublicOnlyViolationError",
    "QuarantineRecord",
    "ROW_LENGTH",
    "RateLimitConfig",
    "RateLimitedError",
    "RestThrottle",
    "RetryConfig",
    "SchemaMismatchError",
    "StreamEvent",
    "TickerEvent",
    "TransactionEvent",
    "TransactionTickEmitter",
    "__version__",
    "bithumb_path_to_symbol",
    "build_transaction_tick_row",
    "compute_payload_hash",
    "normalize_message",
    "normalize_row",
    "symbol_to_bithumb_path",
]

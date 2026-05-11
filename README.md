# mctrader-market-bithumb

Bithumb HTTP adapter for the mctrader platform — public OHLCV endpoint with explicit ADR-009 D3 normalization.

## Status

`v0.1.0` — first commit, MCT-14 Phase 2.

## Public API

```python
from mctrader_market_bithumb import (
    BithumbHttpClient,
    BithumbCandleProvider,
    BithumbApiError,
    RateLimitedError,
    SchemaMismatchError,
    InsufficientCoverageError,
    PublicOnlyViolationError,
)
```

## Candle collector retirement (ADR-026 / MCT-146)

Epic MCT-112 Story-12 (Transaction SSOT cutover) 후 candle 영역의 SSOT 가 전환됨:

- **cutoff 이전** (default `2026-06-01T00:00:00Z`): `BithumbCandleProvider` eager
  REST fetch 가 legacy historic backfill 용도로 **영구 보존** (ADR-026 §D1 immutable SSOT).
- **cutoff 이후**: Bithumb WS transaction subscriber (Story-4, MCT-138) → `mctrader-data`
  transaction WAL → Compactor → Parquet (Aggregation Core Lib, ADR-025) 가 SSOT.
  `mctrader-data` CLI 의 cutoff guard (ADR-026 §D6) 가 candle backfill 침투 차단.

본 repository 에 candle polling collector **daemon 은 부재** — `BithumbCandleProvider`
는 backtest / backfill 시 호출되는 thin REST wrapper. WS transaction subscriber
(`subscribers/transaction_ws.py`) 가 cutoff 이후 ingestion 의 유일 active path.

## Public-only enforcement (ADR-008 D5)

- URL allowlist: `https://api.bithumb.com/public` + candlestick path only
- Runtime header guard: `Authorization` / `Api-Key` / `Api-Sign` / `X-BITHUMB-*` reject
- Source policy lint: `os.getenv` / `Authorization` literal usage X
- 1Password CLI dependency 절대 X

## Bithumb response order (CRITICAL)

```
[timestamp_ms, open, close, high, low, volume]
                       ^^^^^  ^^^^
                       INDEX 2 = close (NOT high)
                       INDEX 3 = high
```

ADR-009 D3 explicit positional mapping table; auto unpacking 금지.

## Related

- [mctrader-market](https://github.com/mclayer/mctrader-market) — `CandleProvider` Protocol
- ADR-008 / ADR-009 / ADR-011

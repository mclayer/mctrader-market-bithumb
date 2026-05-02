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

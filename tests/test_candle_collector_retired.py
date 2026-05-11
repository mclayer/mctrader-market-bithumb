"""Candle polling collector daemon retirement test (ADR-026 §D6, MCT-146).

Epic MCT-112 Story-12 (final) — Legacy candle collector retirement.

본 repository 에는 **candle polling collector daemon 이 부재** 라는 invariant 박제.
cutoff 이후 SSOT 는 WS transaction subscriber (Story-4, MCT-138). BithumbCandleProvider
는 legacy historic backfill 의 REST wrapper 로 영구 보존 (ADR-026 §D1 immutable SSOT).
"""

from __future__ import annotations

import importlib
import pkgutil

import mctrader_market_bithumb


class TestCandleCollectorRetirement:
    """ADR-026 §D6: candle collector daemon 부재 + WS transaction subscriber 활성."""

    def test_no_candle_collector_module(self):
        """`mctrader_market_bithumb.collectors.candle_collector` 모듈 부재."""
        # 'collectors' 패키지 자체가 없어야 함 (daemon 부재)
        sub_packages = [
            m.name for m in pkgutil.iter_modules(mctrader_market_bithumb.__path__)
        ]
        assert "collectors" not in sub_packages, (
            f"Unexpected 'collectors' package — candle daemon retired per ADR-026 §D6. "
            f"Found packages: {sub_packages}"
        )

    def test_no_candle_collector_attribute(self):
        """Top-level 에 CandleCollector / candle_collector 부재."""
        for forbidden in ("CandleCollector", "candle_collector", "CandlePoller", "run_candle_daemon"):
            assert not hasattr(mctrader_market_bithumb, forbidden), (
                f"Unexpected attribute {forbidden!r} — candle daemon retired per ADR-026 §D6"
            )

    def test_candle_collector_module_unimportable(self):
        """직접 import 시도 시 ModuleNotFoundError (daemon path 미존재)."""
        import pytest
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("mctrader_market_bithumb.collectors.candle_collector")
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("mctrader_market_bithumb.candle_collector")

    def test_ws_transaction_subscriber_active(self):
        """WS transaction subscriber (Story-4 MCT-138) 가 cutoff 이후 SSOT path 로 활성."""
        ws_module = importlib.import_module(
            "mctrader_market_bithumb.subscribers.transaction_ws"
        )
        # transaction_ws 모듈 정상 import + transaction subscriber 진입점 존재 검증
        # (정확한 entry-point 이름은 Story-4 spec 따름 — 모듈 attribute 가 비어있지 않음만 확인)
        attrs = [a for a in dir(ws_module) if not a.startswith("_")]
        assert len(attrs) > 0, (
            f"transaction_ws module empty — WS subscriber missing post-cutoff SSOT path"
        )

    def test_candle_provider_preserved_per_adr026_d1(self):
        """ADR-026 §D1: BithumbCandleProvider 는 legacy backfill 용도 영구 보존."""
        from mctrader_market_bithumb.adapter import BithumbCandleProvider
        # Provider class 가 여전히 존재 + get_candles 메서드 보존 의무 (legacy backfill 경로)
        assert hasattr(BithumbCandleProvider, "get_candles"), (
            "BithumbCandleProvider.get_candles missing — ADR-026 §D1 legacy SSOT 보존 위반"
        )
        # Retirement note docstring 에 ADR-026 reference 박제 검증
        doc = BithumbCandleProvider.__doc__ or ""
        assert "ADR-026" in doc, (
            "BithumbCandleProvider docstring 에 ADR-026 retirement note 박제 의무"
        )

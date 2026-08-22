import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.schemas import (
    ExecutionState, Holding, MarketRegimeState, MTFCandidate, TrendQuality,
)


def _base_cand(**overrides):
    cand = MTFCandidate(
        symbol_code="600001.SH",
        symbol_name="测试",
        trade_date="20260818",
        trend_state=overrides.get("trend_state", "S2"),
        trend_quality=overrides.get("trend_quality", "A"),
        market_regime=overrides.get("market_regime", "B"),
        market_regime_state=overrides.get(
            "market_regime_state",
            MarketRegimeState(regime="B", allow_new=True, risk_multiplier=1.0),
        ),
        quality_info=overrides.get("quality_info", TrendQuality(grade="A", score=80, multiplier=1.0)),
        catalyst_info=overrides.get("catalyst_info"),
        technical_factor=overrides.get("technical_factor", {
            "trading_days": 150,
            "ma20_deviation_pct": 5.0,
            "ma20_ge_ma60": True,
            "ma60_5d_slope_pct": 0.2,
            "median_amount_20d": 10000000,
            "close": 10.0,
            "ma60": 9.0,
        }),
    )
    return cand


class ExecutionRiskPositionEnhanceTest(unittest.TestCase):
    def _engine(self):
        return MainTrendEngine(MainTrendConfig.from_yaml())

    def test_gap_penalty_dynamic(self):
        eng = self._engine()
        # C级 + S3 + 无催化高开 -> WAIT
        cand = _base_cand(
            trend_state="S3",
            market_regime="C",
            market_regime_state=MarketRegimeState(regime="C", allow_new=True, risk_multiplier=0.5),
        )
        factor = {"close": 10.0, "open": 10.5, "high": 10.8, "low": 9.9, "vwap_20": 9.8,
                  "volume_ratio": 1.5, "rising_volume": True}
        es = eng.evaluate_execution_from_factor(cand, factor)
        self.assertFalse(es.confirmed)
        self.assertIn("WAIT", es.abandon_reason)
        # A级 + S2 + 催化高开 +5 -> 允许
        cat = {"has_event": True, "score": 80}
        cand2 = _base_cand(
            trend_state="S2",
            market_regime="A",
            market_regime_state=MarketRegimeState(regime="A", allow_new=True, risk_multiplier=1.0),
            catalyst_info=type("Cat", (), {"has_event": True})(),
        )
        factor2 = {"close": 10.5, "open": 10.5, "high": 10.8, "low": 9.9, "vwap_20": 10.2,
                   "volume_ratio": 1.5, "rising_volume": True, "prev_close": 10.0}
        es2 = eng.evaluate_execution_from_factor(cand2, factor2)
        self.assertTrue(es2.confirmed)
        self.assertIn("A级/S2/催化剂高开允许", es2.reasons)

    def test_risk_state_uses_quality_and_exec_confirmation(self):
        eng = self._engine()
        cand = _base_cand(
            trend_quality="A",
            market_regime="B",
            market_regime_state=MarketRegimeState(regime="B", allow_new=True, risk_multiplier=1.0),
            quality_info=TrendQuality(grade="A", score=80, multiplier=1.0),
        )
        cand.technical_factor = {"atr": 0.5, "atr_pct": 5.0, "close": 10.0}
        es_confirmed = ExecutionState(confirmed=True)
        es_wait = ExecutionState(confirmed=False)
        r1 = eng.compute_risk_state(cand, cand.technical_factor, es_confirmed)
        r2 = eng.compute_risk_state(cand, cand.technical_factor, es_wait)
        self.assertGreater(r1.suggested_position_pct or 0, r2.suggested_position_pct or 0)
        self.assertGreater(r1.quality_multiplier, r2.quality_multiplier)

    def test_position_add_requires_profit_and_ma20_exit(self):
        eng = self._engine()
        h_profit = Holding("600001.SH", "测试", "20260818", 10.0, current_price=10.5, highest_price=10.6, holding_days=2)
        d = eng.evaluate_exits([h_profit])[0]
        self.assertEqual(d.state, "ADD")
        self.assertTrue(d.add_allowed)
        h_loss = Holding("600001.SH", "测试", "20260818", 10.0, current_price=9.5, highest_price=11.0, holding_days=2)
        dloss = eng.evaluate_exits([h_loss])[0]
        self.assertFalse(dloss.add_allowed)
        # MA20 break should be exit unless fixed stop hit first. Keep current > stop_pct so MA20 branch is hit.
        h_ma = Holding("600001.SH", "测试", "20260818", 8.0, current_price=7.8, highest_price=11.0, holding_days=3, ma20=8.0, stop_loss_price=7.0)
        dma = eng.evaluate_exits([h_ma])[0]
        self.assertEqual(dma.action, "exit")
        self.assertIn("MA20", dma.reason)


if __name__ == "__main__":
    unittest.main()

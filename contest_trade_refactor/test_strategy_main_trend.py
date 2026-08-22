"""Tests for Main Trend Following Engine (主升浪) final 8-item hard filter + T1 gate."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.strategies import get_strategy, get_strategies
from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.schemas import Holding, MarketRegimeState, MTFCandidate, TrendQuality

def _base_cand(**overrides):
    cand = MTFCandidate(
        symbol_code="600001.SH",
        symbol_name="测试",
        trade_date="20260818",
        trend_state=overrides.get("trend_state", "S2"),
        trend_quality=overrides.get("trend_quality", "A"),
        market_regime=overrides.get("market_regime", "B"),
        market_regime_state=overrides.get("market_regime_state", MarketRegimeState(regime="B", allow_new=True, risk_multiplier=1.0)),
        quality_info=overrides.get("quality_info", TrendQuality(grade="A", score=80, multiplier=1.0)),
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

class MainTrendPackageTest(unittest.TestCase):
    def test_package_registered(self):
        ids = [s.get("id") for s in get_strategies()]
        self.assertIn("main_trend", ids)
        cfg = get_strategy("main_trend")
        self.assertIn("market", cfg)
        self.assertIn("trend", cfg)
        self.assertIn("risk", cfg)
        self.assertTrue(cfg.get("belief_list"))

    def test_hard_filter_passes_all_8(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        cand = _base_cand()
        ok = eng.apply_hard_filter(cand, cand.market_regime_state, liquidity_p20=1_000_000)
        self.assertTrue(ok)
        self.assertTrue(cand.eligible)

    def test_hard_filter_rejects_low_trading_days(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        cand = _base_cand()
        cand.technical_factor["trading_days"] = 100
        ok = eng.apply_hard_filter(cand, cand.market_regime_state, liquidity_p20=1_000_000)
        self.assertFalse(ok)
        self.assertFalse(cand.eligible)

    def test_hard_filter_rejects_close_below_ma20(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        cand = _base_cand()
        cand.technical_factor["ma20_deviation_pct"] = -2.0
        ok = eng.apply_hard_filter(cand, cand.market_regime_state, liquidity_p20=1_000_000)
        self.assertFalse(ok)

    def test_hard_filter_rejects_ma20_le_ma60(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        cand = _base_cand()
        cand.technical_factor["ma20_ge_ma60"] = False
        ok = eng.apply_hard_filter(cand, cand.market_regime_state, liquidity_p20=1_000_000)
        self.assertFalse(ok)

    def test_hard_filter_rejects_negative_ma60_slope(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        cand = _base_cand()
        cand.technical_factor["ma60_5d_slope_pct"] = -0.1
        ok = eng.apply_hard_filter(cand, cand.market_regime_state, liquidity_p20=1_000_000)
        self.assertFalse(ok)

    def test_hard_filter_rejects_bad_trend_state(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        cand = _base_cand()
        cand.trend_state = "S0"
        ok = eng.apply_hard_filter(cand, cand.market_regime_state, liquidity_p20=1_000_000)
        self.assertFalse(ok)

    def test_hard_filter_rejects_low_liquidity(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        cand = _base_cand()
        cand.technical_factor["median_amount_20d"] = 500_000
        ok = eng.apply_hard_filter(cand, cand.market_regime_state, liquidity_p20=1_000_000)
        self.assertFalse(ok)

    def test_market_regime_d_forbid_new(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        mr = eng.evaluate_market_regime("20260818", market_context={"breadth_pct": 0.2, "market_trend": "down", "risk_sentiment": "risk_off"})
        self.assertFalse(mr.allow_new)
        self.assertEqual(mr.regime, "D")
        self.assertAlmostEqual(mr.risk_multiplier, 0.0, places=5)

    def test_exit_stop_loss_and_add(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        h = Holding("600001.SH", "测试", "20260818", 10.0, current_price=9.1, highest_price=10.5, holding_days=3)
        self.assertEqual(eng.evaluate_exits([h])[0].action, "sell")
        h2 = Holding("600001.SH", "测试", "20260818", 10.0, current_price=11.0, highest_price=11.2, holding_days=2)
        self.assertEqual(eng.evaluate_exits([h2])[0].state, "ADD")


if __name__ == "__main__":
    unittest.main()


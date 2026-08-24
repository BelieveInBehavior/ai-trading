"""Tests for Main Trend Following Engine (主升浪) final 8-item hard filter + T1 gate."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.strategies import get_strategy, get_strategies
from utils.factor_dedup import family_dedup_report
from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine, _enrich_residual_rs, _percentile_rank_100
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
        # 默认废除固定 ±6%；用 MA20 生命线触发 EXIT
        h = Holding("600001.SH", "测试", "20260818", 10.0, current_price=9.1, highest_price=10.5, holding_days=3, ma20=9.8)
        self.assertEqual(eng.evaluate_exits([h])[0].action, "exit")
        h2 = Holding("600001.SH", "测试", "20260818", 10.0, current_price=11.0, highest_price=11.2, holding_days=2)
        self.assertEqual(eng.evaluate_exits([h2])[0].state, "ADD")

    def test_enrich_residual_rs_fields(self):
        factor = {
            "stock_return_20d_pct": 12.0,
            "benchmark_return_20d_pct": 5.0,
            "stock_return_60d_pct": 20.0,
            "benchmark_return_60d_pct": 8.0,
            "change_pct": 3.0,
            "sector_1d_return": 1.0,
            "ret_3d_pct": 9.0,
            "sector_3d_return": 6.0,
            "ret_5d_pct": 12.0,
            "sector_5d_return": 7.0,
            "ret_10d_pct": 20.0,
            "sector_10d_return": 12.0,
        }
        out = _enrich_residual_rs(factor)
        # 无 true OLS 残差时不再把简单超额收益命名为 residual（金融口径避免物名不符）。
        self.assertNotIn("residual_rs_vs_index_20d", out)
        self.assertNotIn("residual_rs_vs_index_60d", out)
        self.assertEqual(out["excess_rs_vs_index_20d"], 7.0)
        self.assertEqual(out["excess_rs_vs_index_60d"], 12.0)
        self.assertEqual(out["excess_rs_vs_sector_1d"], 2.0)
        self.assertEqual(out["excess_rs_vs_sector_5d"], 5.0)
        self.assertEqual(out["excess_rs_vs_index"], 7.0)
        self.assertEqual(out["excess_rs_vs_sector"], 5.0)
        self.assertNotIn("residual_rs_vs_sector", out)


if __name__ == "__main__":
    unittest.main()



class MainTrendLayer2EnhancedTest(unittest.TestCase):
    def _engine(self):
        return MainTrendEngine(MainTrendConfig.from_yaml())

    def _factor(self, **over):
        f = {
            "symbol_code": "600001.SH",
            "symbol_name": "测试",
            "close": 10.0,
            "ma20_deviation_pct": 5.0,
            "ma20_ge_ma60": True,
            "ma60": 9.0,
            "ma5_slope_pct": 1.0,
            "breakout_20d": True,
            "breakout_60d": False,
            "close_above_ma5": True,
            "volume_ratio": 1.5,
            "amount_ratio": 1.4,
            "ret_5d_pct": 6.0,
            "ret_20d_pct": 25.0,
            "rsi": 65.0,
            "atr_pct": 4.0,
            "close_vs_20d_high_pct": 0.0,
            "weekly_trend_score": 75.0,
            "relative_strength_score": 60.0,
            "relative_strength_20d_pct": 8.0,
            "relative_strength_60d_pct": 12.0,
            "vwap_20": 9.5,
            "vwap": 9.5,
        }
        f.update(over)
        return f

    def test_s1_uses_cost_aux_only(self):
        eng = self._engine()
        # S1 without close above MA20 proxy cost (breakout base met) should still be tradeable
        f = self._factor(
            breakout20=True, volume_ratio=1.3, ma5_slope_pct=1.0,
            relative_strength_score=56, close=10.0, ma20_deviation_pct=-0.5,
            close_vs_20d_high_pct=0.0,
        )
        # This would trigger S5 if below ma20 and RSI <45, so keep RSI high
        f["rsi"]=60.0
        ts = eng.assess_trend_state(f)
        self.assertEqual(ts.state, "S1")
        self.assertTrue(ts.tradeable)
        # If cost proxy is ok, S1 gets bonus and reason
        f2 = self._factor(
            close=10.5, ma20_deviation_pct=4.0, volume_ratio=1.3, ma5_slope_pct=1.0,
            relative_strength_score=56.0, breakout_20d=True, vwap_20=9.0,
        )
        ts2 = eng.assess_trend_state(f2)
        self.assertEqual(ts2.state, "S1")
        self.assertTrue(any("站上关键成本区(辅助)" in r for r in ts2.reasons))

    def test_s3_allowed_without_new_high(self):
        eng = self._engine()
        f = self._factor(
            ma20_deviation_pct=2.0,
            volume_ratio=0.8,
            breakout_20d=True,
            close_vs_20d_high_pct=-3.0,  # 未创新高但仍是中继
            relative_strength_score=52,
            ret_20d_pct=15.0,
            rsi=55.0,
        )
        ts = eng.assess_trend_state(f)
        self.assertEqual(ts.state, "S3")
        self.assertTrue(ts.tradeable)

    def test_s4_multidim_rs_decline_and_sector_weak(self):
        eng = self._engine()
        f = self._factor(
            ma20_deviation_pct=5.0,
            ret_20d_pct=35.0,
            close_vs_20d_high_pct=-1.0,
            relative_strength_20d_pct=4.0,
            relative_strength_60d_pct=12.0,
            volume_ratio=1.8,
            rsi=75.0,
            sector_1d_return=-1.5,
        )
        ts = eng.assess_trend_state(f)
        self.assertEqual(ts.state, "S4")
        self.assertFalse(ts.tradeable)
        self.assertIn("板块转弱", "".join(ts.reasons))

    def test_s5_breakout_below_ma20_weak_rsi(self):
        eng = self._engine()
        f = self._factor(
            close=9.5, ma20_deviation_pct=-2.0, rsi=40.0,
            volume_ratio=1.0, breakout_20d=False, close_vs_20d_high_pct=-8.0,
            ret_20d_pct=-5.0,
        )
        ts = eng.assess_trend_state(f)
        self.assertEqual(ts.state, "S5")
        self.assertFalse(ts.tradeable)
        self.assertEqual(ts.action_hint, "EXIT")

    def test_exit_atr_trailing_stop_triggered(self):
        eng = self._engine()
        h = Holding(
            "600001.SH", "测试", "20260818", entry_price=10.0,
            current_price=9.41, highest_price=11.5, holding_days=3,
            atr_trailing_stop=9.45,
        )
        d = eng.evaluate_exits([h])[0]
        self.assertTrue(d.atr_trailing_stop_triggered)
        self.assertEqual(d.action, "exit")

    def test_recapture_exit(self):
        eng = self._engine()
        h = Holding(
            "600001.SH", "测试", "20260818", entry_price=10.0,
            current_price=9.45, highest_price=11.0, holding_days=1,
            prev_close=9.43, stop_loss_price=9.5,
        )
        d = eng.evaluate_exits([h])[0]
        self.assertTrue(d.recapture_triggered)

    def test_enrich_residual_rs_fields(self):
        factor = {
            "stock_return_20d_pct": 12.0,
            "benchmark_return_20d_pct": 5.0,
            "stock_return_60d_pct": 20.0,
            "benchmark_return_60d_pct": 8.0,
            "change_pct": 3.0,
            "sector_1d_return": 1.0,
            "ret_3d_pct": 9.0,
            "sector_3d_return": 6.0,
            "ret_5d_pct": 12.0,
            "sector_5d_return": 7.0,
            "ret_10d_pct": 20.0,
            "sector_10d_return": 12.0,
        }
        out = _enrich_residual_rs(factor)
        # 无 true OLS 残差时不再把简单超额收益命名为 residual（金融口径避免物名不符）。
        self.assertNotIn("residual_rs_vs_index_20d", out)
        self.assertNotIn("residual_rs_vs_index_60d", out)
        self.assertEqual(out["excess_rs_vs_index_20d"], 7.0)
        self.assertEqual(out["excess_rs_vs_index_60d"], 12.0)
        self.assertEqual(out["excess_rs_vs_sector_1d"], 2.0)
        self.assertEqual(out["excess_rs_vs_sector_5d"], 5.0)
        self.assertEqual(out["excess_rs_vs_index"], 7.0)
        self.assertEqual(out["excess_rs_vs_sector"], 5.0)
        self.assertNotIn("residual_rs_vs_sector", out)


if __name__ == "__main__":
    unittest.main()


class CrossSectionalRSHelperTest(unittest.TestCase):
    def test_percentile_rank_100(self):
        values = [0.0, 10.0, 20.0, 30.0, 40.0]
        self.assertEqual(_percentile_rank_100(20.0, values), 50.0)
        self.assertEqual(_percentile_rank_100(10.0, values), 30.0)
        self.assertEqual(_percentile_rank_100(0.0, values), 10.0)
        self.assertIsNone(_percentile_rank_100(None, values))
        self.assertIsNone(_percentile_rank_100(5.0, []))


if __name__ == "__main__":
    unittest.main()


class S2SectorDowngradeTest(unittest.TestCase):
    def _engine(self):
        return MainTrendEngine(MainTrendConfig.from_yaml())

    def _s2_factor(self, **over):
        f = {
            "symbol_code": "600001.SH", "symbol_name": "测试",
            "close": 10.0, "ma20_deviation_pct": 5.0, "ma20_ge_ma60": True,
            "ma60": 9.0, "ma5_slope_pct": 1.0, "ma5_gt_ma20": True,
            "close_above_ma5": True, "breakout_20d": True, "breakout_60d": False,
            "volume_ratio": 1.2, "ret_5d_pct": 6.0, "ret_20d_pct": 25.0,
            "rsi": 65.0, "atr_pct": 4.0, "close_vs_20d_high_pct": 0.0,
            "weekly_trend_score": 75.0, "relative_strength_score": 60.0,
            "relative_strength_20d_pct": 8.0, "relative_strength_60d_pct": 12.0,
            "vwap_20": 9.5, "vwap": 9.5,
            "sector_1d_return": -1.5, "sector_rank": 80, "sector_5d_return": -2.0,
        }
        f.update(over)
        return f

    def test_s2_sector_weak_degrades_not_hard_reject_when_s3_met(self):
        eng = self._engine()
        f = self._s2_factor(volume_ratio=1.0, close_vs_20d_high_pct=0.0,
                            relative_strength_20d_pct=13.0, relative_strength_60d_pct=12.0)
        # 板块弱触发降级（sector_5d 负、sector_rank 80），volume=1.0 同时满足 S2 量门槛(>=0.9)与 S3 缩量上限(<=1.0)
        # -> 应降为 S3 而非 S2；rs20>=rs60 避免误触发 S4
        ts = eng.assess_trend_state(f)
        self.assertEqual(ts.state, "S3")
        self.assertTrue(ts.tradeable)
        self.assertTrue(any("降级" in r for r in ts.reasons))

    def test_s2_sector_ok_keeps_s2(self):
        eng = self._engine()
        f = self._s2_factor(sector_1d_return=2.0, sector_rank=5, sector_5d_return=3.0)
        ts = eng.assess_trend_state(f)
        self.assertEqual(ts.state, "S2")
        self.assertTrue(ts.tradeable)

    def test_s2_sector_missing_lenient(self):
        eng = self._engine()
        f = self._s2_factor(sector_1d_return=None, sector_rank=None, sector_5d_return=None)
        ts = eng.assess_trend_state(f)
        self.assertEqual(ts.state, "S2")


if __name__ == "__main__":
    unittest.main()

class FactorFamilyDedupTest(unittest.TestCase):
    def test_report_rejects_redundant_momentum(self):
        factors = []
        for i in range(60):
            base = i * 0.2
            factors.append({
                "ret_5d_pct": base + (i % 7) * 0.3,
                "ret_10d_pct": base + (i % 7) * 0.31 + 0.01 * (i % 11),
                "ret_20d_pct": base + (i % 7) * 0.55 + 0.02 * (i % 13),
                "relative_strength_20d_pct": base + (i % 7) * 0.1,
                "residual_rs_vs_index_20d": base + 1.0 + 0.01 * (i % 7),
                "ma20_deviation_pct": base + 2.0 + 0.01 * (i % 5),
                "volume_ratio": 1.0 + (i % 5) * 0.2,
            })
        report = family_dedup_report(factors, corr_threshold=0.85)
        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["correlation"]["high_corr_pairs"])
        # 动量族不应 5d/10d/20d 全部被选为代表。
        mem_reps = report["representatives"].get("momentum") or []
        self.assertLessEqual(len(mem_reps), 2)
        vif = report["vif"]
        self.assertTrue(any(v is not None and v > 5 for v in vif.values()))

    def test_vif_table_on_low_sample_is_none(self):
        from utils.factor_dedup import vif_table
        factors = [{"ret_5d_pct": 1.0, "ret_10d_pct": 2.0}]
        self.assertEqual(vif_table(factors), {"ret_5d_pct": None, "ret_10d_pct": None})


class CatalystReactionTest(unittest.TestCase):
    def _engine(self):
        return MainTrendEngine(MainTrendConfig.from_yaml())

    def test_no_catalyst_defaults_neutral(self):
        c = self._engine().assess_catalyst({})
        self.assertFalse(c.has_event)
        self.assertEqual(c.score, 50.0)

    def test_strong_event_with_price_reaction_not_nullified_by_close_open(self):
        # 即使 Close<Open 但实际/预期收益为正，不应被“收阴=失效”直接归零
        factor = {
            "catalyst": {
                "event_type": "major_order",
                "event_level": "S",
                "freshness": 0.9,
                "company_specific": True,
                "earnings_impact": 0.8,
                "credibility": 0.95,
                "price_reaction": "positive",
                "source_quality": "official",
                "expected_return_pct": 5.0,
                "actual_return_pct": 8.0,
            },
            "open": 10.0,
            "close": 9.8,  # close < open
            "change_pct": 8.0,
        }
        c = self._engine().assess_catalyst(factor)
        self.assertTrue(c.has_event)
        self.assertGreater(c.score, 75)
        self.assertIn("实际/预期收益=1.60", c.reasons)

    def test_weak_reaction_scores_lower_than_strong(self):
        eng = self._engine()
        strong = {"catalyst": {"event_type": "major_order", "event_level": "S", "freshness": 0.9,
                               "company_specific": True, "credibility": 0.95, "price_reaction": "positive",
                               "expected_return_pct": 5.0, "actual_return_pct": 8.0}}
        weak = {"catalyst": {"event_type": "major_order", "event_level": "B", "freshness": 0.2,
                              "company_specific": False, "credibility": 0.4, "price_reaction": "negative",
                              "expected_return_pct": 5.0, "actual_return_pct": -4.0}}
        self.assertGreater(eng.assess_catalyst(strong).score, eng.assess_catalyst(weak).score)


if __name__ == "__main__":
    unittest.main()

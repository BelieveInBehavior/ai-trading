"""T日分层：PreScore / 动态止损 / 主题敞口 / T日不得 BUY。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.execution_manual import grade_execution
from strategies.main_trend.portfolio import apply_theme_caps, theme_of
from strategies.main_trend.schemas import CatalystState, HotMoneyState, MarketRegimeState, MarketSentimentState, MTFCandidate, SectorState, TrendQuality
from strategies.main_trend.scoring import compute_pre_score, compute_stops, compute_final_score
from strategies.main_trend.tday import rebuild_from_result
from scripts.main_trend_event_backtest import _apply_factor_overrides


def _cand(**over):
    return MTFCandidate(
        symbol_code=over.get("symbol_code", "600988"),
        symbol_name=over.get("symbol_name", "赤峰黄金"),
        trade_date="20260821",
        trend_state=over.get("trend_state", "S2"),
        trend_quality="A",
        market_regime="C",
        sector_name=over.get("sector_name", "贵金属"),
        catalyst_score=50.0,
        eligible=True,
        market_regime_state=MarketRegimeState(regime="C", allow_new=True, risk_multiplier=0.5, score=47),
        quality_info=TrendQuality(grade="A", score=over.get("quality", 90.0), multiplier=1.0),
        sector_info=SectorState(sector_name=over.get("sector_name", "贵金属"), score=over.get("sector_score", 75.0), grade="A", passed=True),
        catalyst_info=CatalystState(has_event=False, score=50.0),
        technical_factor={
            "close": over.get("close", 49.43),
            "atr": over.get("atr", 2.0),
            "atr_pct": over.get("atr_pct", 4.0),
            "ma20": over.get("ma20", 46.0),
            "ma20_deviation_pct": 7.0,
        },
    )


class PreScoreTest(unittest.TestCase):
    def test_s2_cluster_not_all_100(self):
        a = compute_pre_score(trend_state="S2", quality_score=92, sector_score=80, sector_grade="A", catalyst_score=50, has_event=False)
        b = compute_pre_score(trend_state="S2", quality_score=80, sector_score=70, sector_grade="A", catalyst_score=50, has_event=False)
        c = compute_pre_score(trend_state="S1", quality_score=70, sector_score=55, sector_grade="B", catalyst_score=50, has_event=False)
        self.assertLess(a["pre_score"], 100)
        self.assertLess(b["pre_score"], a["pre_score"])
        self.assertLess(c["pre_score"], b["pre_score"])
        self.assertEqual(a["catalyst_score"], 50.0)
        self.assertEqual(a["catalyst_grade"], "B")

    def test_pre_score_short_sprint_uses_sentiment_and_hot_money(self):
        scores = compute_pre_score(
            trend_state="S2",
            quality_score=90,
            sector_score=70,
            sector_grade="A",
            market_sentiment_score=80,
            hot_money_score=40,
            catalyst_score=50,
            has_event=False,
        )
        # trend_component(S2, 90)=93; weighted:
        # 93*40% + 70*25% + 80*15% + 40*10% + 50*10% = 75.7
        self.assertAlmostEqual(scores["pre_score"], 75.7, places=2)
        self.assertEqual(scores["market_sentiment_grade"], "A")
        self.assertEqual(scores["hot_money_grade"], "C")

    def test_final_score_needs_execution(self):
        pre = 80.0
        self.assertEqual(compute_final_score(pre, None), 80.0)
        self.assertGreater(compute_final_score(pre, 90), pre)
        self.assertLess(compute_final_score(pre, 40), pre)
        self.assertEqual(compute_final_score(80, 90), 84.0)

    def test_macd_is_light_quality_factor_not_gate(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        market = MarketRegimeState(regime="B", allow_new=True, risk_multiplier=1.0, score=60)
        base = {
            "ma20_deviation_pct": 5.0,
            "breakout_20d": True,
            "ret_5d_pct": 6.0,
            "ret_10d_pct": 9.0,
            "relative_strength_score": 70.0,
            "volume_ratio": 1.4,
            "atr_pct": 4.0,
            "hh_hl_strict": True,
        }
        trend = eng.assess_trend_state({
            **base,
            "close": 10.0,
            "ma20_ge_ma60": True,
            "ma5_gt_ma20": True,
            "ma5_slope_pct": 1.0,
            "close_above_ma5": True,
            "close_vs_20d_high_pct": 0.0,
        })
        weak = eng.assess_trend_quality({**base, "macd_hist": -0.2, "macd_hist_delta": -0.05}, trend, market)
        strong = eng.assess_trend_quality({**base, "macd_hist": 0.2, "macd_hist_delta": 0.05}, trend, market)
        self.assertIn("macd_momentum", strong.family)
        self.assertGreater(strong.score, weak.score)
        self.assertLess(strong.score - weak.score, 4.0)


class SentimentHotMoneyTest(unittest.TestCase):
    def test_ablation_overrides_disable_weights_and_flags(self):
        cfg = _apply_factor_overrides(
            MainTrendConfig.from_yaml(),
            enable_market_sentiment=False,
            enable_hot_money=False,
            ablation_tag="baseline_core",
        )
        self.assertFalse(cfg.sentiment.get("enabled"))
        self.assertFalse(cfg.hot_money.get("enabled"))
        self.assertEqual(float(cfg.scoring.get("market_sentiment_weight") or 0.0), 0.0)
        self.assertEqual(float(cfg.scoring.get("hot_money_weight") or 0.0), 0.0)
        self.assertEqual(str((cfg.backtest or {}).get("ablation_tag")), "baseline_core")

    def test_market_sentiment_d_blocks_new_position_and_cuts_risk(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        sentiment = eng.assess_market_sentiment("20260821", {
            "limit_up_count": 12,
            "break_count": 8,
            "max_board": 1,
            "one_word_limit_up_count": 8,
        })
        self.assertEqual(sentiment.grade, "D")
        cand = _cand()
        cand.market_sentiment_state = sentiment
        cand.hot_money_state = HotMoneyState(score=50, grade="B", passed=True)
        ok = eng.apply_hard_filter(cand, cand.market_regime_state)
        self.assertFalse(ok)
        self.assertIn("market_sentiment:D", cand.reasons)
        risk = eng.compute_risk_state(cand, cand.technical_factor, None)
        self.assertLess(risk.account_risk_pct, cand.market_regime_state.risk_multiplier)

    def test_hot_money_net_sell_penalizes_entry_score(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        weak_hot = eng.assess_hot_money_state({
            "symbol_code": "600000",
            "lhb_net_buy_amount": -500_000_000,
            "institution_net_buy": -200_000_000,
        }, "20260821")
        self.assertEqual(weak_hot.grade, "D")
        self.assertIn(weak_hot.risk_flag, {"lhb_net_sell", "institution_net_sell", "hot_money_weak"})
        base = _cand()
        base.market_sentiment_state = MarketSentimentState(score=50, grade="B", available=False)
        base.hot_money_state = HotMoneyState(score=50, grade="B", passed=True)
        weak = _cand()
        weak.market_sentiment_state = base.market_sentiment_state
        weak.hot_money_state = weak_hot
        self.assertLess(eng._candidate_entry_score(weak), eng._candidate_entry_score(base))


class DynamicStopTest(unittest.TestCase):
    def test_no_fixed_six_percent(self):
        stops = compute_stops(80.78, atr=3.2, ma20=76.0, initial_atr_mult=2.5, trail_atr_mult=3.0)
        self.assertAlmostEqual(stops["initial_stop"], 80.78 - 2.5 * 3.2, places=3)
        self.assertNotAlmostEqual(stops["initial_stop"], 80.78 * 0.94, places=2)
        self.assertIsNone(stops.get("take_profit"))
        self.assertAlmostEqual(stops["target_price_1"], 80.78 + 1.5 * 3.2, places=3)
        self.assertAlmostEqual(stops["target_price_2"], 80.78 + 2.5 * 3.2, places=3)
        self.assertEqual(stops["target_method"], "atr_1.5_2.5")
        self.assertAlmostEqual(stops["trailing_stop"], 80.78 - 3.0 * 3.2, places=3)
        self.assertEqual(stops["highest_close"], 80.78)


class ThemeExposureTest(unittest.TestCase):
    def test_gold_names_same_theme(self):
        self.assertEqual(theme_of("贵金属", "赤峰黄金"), "贵金属")
        self.assertEqual(theme_of("小金属", "金徽股份"), "贵金属")
        self.assertEqual(theme_of("港口航运", "中远海控"), "航运物流")
        self.assertEqual(theme_of("化学纤维", "桐昆股份"), "石化化工")

    def test_theme_cap_keeps_three(self):
        rows = [
            {"theme": "贵金属", "pre_score": 90 - i, "raw_position_pct": 5.0, "symbol_name": n}
            for i, n in enumerate(["赤峰黄金", "山东黄金", "西部黄金", "山金国际", "中金黄金"])
        ]
        out = apply_theme_caps(rows, theme_cap_pct=12.0, max_names_per_theme=3)
        kept = [r for r in out if r["portfolio_state"] != "THEME_CAP"]
        capped = [r for r in out if r["portfolio_state"] == "THEME_CAP"]
        self.assertEqual(len(kept), 3)
        self.assertEqual(len(capped), 2)
        self.assertLessEqual(sum(r["suggested_position_pct"] for r in kept), 12.01)


class TDayNoBuyTest(unittest.TestCase):
    def test_tday_signals_are_wait(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        cands = [_cand(), _cand(symbol_code="600547", symbol_name="山东黄金", close=37.05)]
        tday = eng.build_tday_pool(cands, "20260821")
        signals = eng.build_buy_signals(cands, "20260821", phase="tday", tday_rows=tday["pool"])
        self.assertTrue(all(s.t1_state == "WAIT" for s in signals))
        self.assertTrue(all(not s.buy_ready for s in signals))
        self.assertTrue(all(s.lifecycle_state == "WAIT" for s in signals))
        self.assertTrue(all(r["action"] == "WAIT" for r in tday["pool"]))
        self.assertLess(max(r["pre_score"] for r in tday["pool"]), 100)

    def test_rebuild_from_result_wait(self):
        result = {
            "trade_date": "20260821",
            "discovery": {
                "eligible": [
                    {
                        "symbol_code": "600988",
                        "symbol_name": "赤峰黄金",
                        "trade_date": "20260821",
                        "trend_state": "S2",
                        "sector_name": "贵金属",
                        "catalyst_score": 50,
                        "trend_quality_info": {"score": 90},
                        "sector_state": {"score": 80, "grade": "A", "sector_name": "贵金属"},
                        "catalyst_state": {"score": 50, "has_event": False},
                    }
                ]
            },
            "buy_signals": [
                {
                    "symbol_code": "600988",
                    "suggested_position_pct": 4.2,
                    "gates": {
                        "execution": {"detail": {"detail": {"price": 49.43}}},
                        "risk": {"detail": {"stop_distance_pct": 10.0, "stop_distance_abs": 4.94, "suggested_position_pct": 4.2}},
                    },
                }
            ],
        }
        out = rebuild_from_result(result)
        self.assertEqual(out["pool"][0]["t1_state"], "WAIT")
        self.assertEqual(out["pool"][0]["reference_price"], 49.43)
        self.assertIsNone(out["pool"][0]["entry_price"])


class ManualExecutionTest(unittest.TestCase):
    def test_strong_vs_weak(self):
        strong = grade_execution(
            open_px=50.0, price_0935=50.6, prev_close=49.4,
            auction_amount=120_000_000, index_change_pct=1.1, sector_change_pct=2.8,
            bid_support="强", vwap=50.2,
        )
        weak = grade_execution(
            open_px=38.8, price_0935=37.9, prev_close=37.05,
            auction_amount=20_000_000, index_change_pct=1.1, sector_change_pct=2.8,
            bid_support="弱", vwap=38.5,
        )
        self.assertEqual(strong["action"], "BUY")
        self.assertEqual(strong["execution_grade"], "A")
        self.assertEqual(weak["action"], "WAIT")
        self.assertEqual(weak["execution_grade"], "C")


if __name__ == "__main__":
    unittest.main()

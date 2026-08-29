"""Tests for the V1 main_trend Exit state machine (P0-P4), supporting CLI-style holdings."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.main_trend.engine import _enrich_residual_rs, MainTrendConfig, MainTrendEngine
from strategies.main_trend.schemas import Holding


def make_engine():
    return MainTrendEngine(MainTrendConfig.from_yaml())


def holdings_from_rows(rows):
    out = []
    for r in rows:
        out.append(Holding(
            symbol_code=r.get("symbol_code", ""),
            symbol_name=r.get("symbol_name", ""),
            entry_date=r.get("entry_date", ""),
            entry_price=float(r.get("entry_price", 0) or 0),
            current_price=float(r.get("current_price") or 0),
            holding_days=int(r.get("holding_days", 0) or 0),
            highest_price=float(r.get("highest_price") or 0),
            highest_close=float(r.get("highest_close") or 0),
            ma10=float(r.get("ma10") or 0) if r.get("ma10") not in (None, 0, "") else None,
            ma20=float(r.get("ma20") or 0) if r.get("ma20") not in (None, 0, "") else None,
            prev_close=float(r.get("prev_close") or 0) if r.get("prev_close") not in (None, 0, "") else None,
            prev_ma20=float(r.get("prev_ma20") or 0) if r.get("prev_ma20") not in (None, 0, "") else None,
            atr_trailing_stop=float(r.get("atr_trailing_stop") or 0) if r.get("atr_trailing_stop") not in (None, 0, "") else None,
            trade_plan=r.get("trade_plan") or {},
            realtime_quote=r.get("realtime_quote") or {},
            event_catalyst=r.get("event_catalyst"),
            stop_loss_price=float(r.get("stop_loss_price") or 0) if r.get("stop_loss_price") not in (None, 0, "") else None,
            trend_state=str(r.get("trend_state") or (r.get("trade_plan") or {}).get("trend_state") or ""),
            trend_state_info=r.get("trend_state_info") or {},
            previous_trend_state=str(r.get("previous_trend_state") or ""),
            trend_state_streak=int(r.get("trend_state_streak") or 0),
            trend_reason_code=str(r.get("trend_reason_code") or ""),
            trend_confidence=float(r.get("trend_confidence") or 0),
        ))
    return out


class MainTrendExitStateMachineTest(unittest.TestCase):
    def test_ma20_first_day_below_is_immediate_sell_v2(self):
        """V2.0：Close 首次跌破 MA20 即无条件清仓，不再等双日确认。"""
        eng = make_engine()
        rows = [{
            "symbol_code": "000001", "symbol_name": "测", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 9.5, "highest_price": 9.55,
            "highest_close": 9.55, "ma20": 9.8, "prev_close": 10.0, "prev_ma20": 9.7,
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "exit")
        self.assertEqual(d.exit_class, "SELL_CONFIRM")
        self.assertIn("无条件清仓", d.reason)

    def test_ma10_first_day_below_but_above_ma20_reduces_50(self):
        """V2.0：Close<MA10 但仍在 MA20 之上 -> 减仓 50%。"""
        eng = make_engine()
        rows = [{
            "symbol_code": "000002", "symbol_name": "测", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 9.4, "highest_price": 11.0,
            "highest_close": 11.0, "ma10": 9.6, "ma20": 9.0,
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "reduce")
        self.assertEqual(d.exit_class, "REDUCE")
        self.assertAlmostEqual(d.reduce_pct, 50.0, places=3)

    def test_first_s0_after_s1_watches_even_above_ma20(self):
        """T日是主升候选，T+1刷新为非S1/S2/S3时不能继续普通HOLD。"""
        eng = make_engine()
        rows = [{
            "symbol_code": "000002", "symbol_name": "测", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 10.8, "highest_price": 11.0,
            "highest_close": 11.0, "ma10": 10.2, "ma20": 9.6,
            "trend_state": "S0", "previous_trend_state": "S1", "trend_state_streak": 1,
            "trend_reason_code": "NORMAL_PULLBACK",
            "trade_plan": {"trend_state": "S0", "trend_state_reasons": ["正常回踩"]},
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "hold")
        self.assertEqual(d.position_state, "WATCH")
        self.assertEqual(d.exit_class, "HOLD")
        self.assertEqual(d.trend_state, "S0")
        self.assertIn("进入WATCH", d.reason)

    def test_second_s0_after_s1_reduces(self):
        rows = [{
            "symbol_code": "000003", "symbol_name": "测连续S0", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 10.5, "highest_price": 11.0,
            "highest_close": 11.0, "ma10": 10.2, "ma20": 9.6,
            "trend_state": "S0", "previous_trend_state": "S0", "trend_state_streak": 2,
            "trend_reason_code": "MOMENTUM_LOSS",
        }]
        d = make_engine().evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "reduce")
        self.assertEqual(d.reduce_pct, 40.0)
        self.assertIn("连续2日", d.reason)

    def test_third_s0_with_two_independent_weak_signals_exits(self):
        rows = [{
            "symbol_code": "000004", "symbol_name": "测持续退化", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 10.5, "highest_price": 11.0,
            "highest_close": 11.0, "ma10": 10.2, "ma20": 9.6,
            "trend_state": "S0", "previous_trend_state": "S0", "trend_state_streak": 3,
            "trend_reason_code": "MOMENTUM_LOSS",
            "trade_plan": {
                "ma10_slope_pct": -0.2, "ma20_slope_pct": -0.1,
                "relative_strength_20d_pct": 2.0, "relative_strength_60d_pct": 8.0,
            },
        }]
        d = make_engine().evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "exit")
        self.assertEqual(d.holding_health, "WEAKENING")
        self.assertGreaterEqual(len(d.holding_health_signals), 2)

    def test_third_s0_without_weak_confirmation_only_reduces(self):
        rows = [{
            "symbol_code": "000005", "symbol_name": "测缩量整理", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 10.5, "highest_price": 11.0,
            "highest_close": 11.0, "ma10": 10.2, "ma20": 9.6,
            "trend_state": "S0", "previous_trend_state": "S0", "trend_state_streak": 3,
            "trend_reason_code": "NORMAL_PULLBACK",
            "trade_plan": {"ma10_slope_pct": 0.2, "ma20_slope_pct": 0.1, "relative_strength_score": 65.0},
        }]
        d = make_engine().evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "reduce")
        self.assertEqual(d.holding_health, "HEALTHY")

    def test_key_support_break_exits_even_above_ma20(self):
        rows = [{
            "symbol_code": "000006", "symbol_name": "测关键低点", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 10.0, "highest_price": 11.0,
            "highest_close": 11.0, "ma10": 10.2, "ma20": 9.5,
            "trend_state": "S3", "trend_state_streak": 1,
            "trade_plan": {"support_1": 10.1, "ma10_slope_pct": 0.1},
        }]
        d = make_engine().evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "exit")
        self.assertIn("key_support_broken", d.holding_health_signals)

    def test_s5_trend_state_exits_even_above_ma20(self):
        eng = make_engine()
        rows = [{
            "symbol_code": "000003", "symbol_name": "测", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 10.8, "highest_price": 11.0,
            "highest_close": 11.0, "ma10": 10.2, "ma20": 9.6,
            "trade_plan": {"trend_state": "S5", "trend_state_reasons": ["趋势破坏"]},
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "exit")
        self.assertEqual(d.exit_class, "SELL_CONFIRM")
        self.assertEqual(d.trend_state, "S5")
        self.assertIn("TrendState=S5", d.reason)

    def test_ma20_second_day_below_sell_confirm(self):
        eng = make_engine()
        rows = [{
            "symbol_code": "000001", "symbol_name": "测", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 9.3, "highest_price": 11.0,
            "ma20": 9.8, "prev_close": 9.5, "prev_ma20": 9.7,
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "exit")
        self.assertEqual(d.exit_class, "SELL_CONFIRM")
        self.assertEqual(d.exit_level, "P1")

    def test_trailing_stop_max_6_or_2atr_sell(self):
        eng = make_engine()
        # highest_close=100 -> trail = 100 - 6% = 94; current 93 -> sell trail
        rows = [{
            "symbol_code": "000002", "symbol_name": "测", "entry_date": "20260818",
            "entry_price": 80.0, "current_price": 93.0, "highest_price": 102.0,
            "highest_close": 100.0, "ma20": 90.0,
            "realtime_quote": {"atr_pct": 2.0},
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.exit_class, "SELL_TRAILING")
        self.assertLess(d.trailing_stop_price, 94.0 + 1e-9)
        self.assertGreater(d.trailing_stop_price, 93.5)

    def test_trailing_stop_2atr_wider_for_high_vol(self):
        eng = make_engine()
        # ATR 5% => 2*5%=10% > 6%; highest_close=100 -> trail=90; current=91 no sell
        rows = [{
            "symbol_code": "000003", "symbol_name": "测", "entry_date": "20260818",
            "entry_price": 80.0, "current_price": 91.0, "highest_price": 102.0,
            "highest_close": 100.0, "ma20": 85.0,
            "realtime_quote": {"atr_pct": 5.0},
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertNotEqual(d.exit_class, "SELL_TRAILING")
        self.assertAlmostEqual(d.trailing_stop_price, 90.0, places=3)

    def test_reduce_on_two_decay_signals(self):
        eng = make_engine()
        # no new high + sector weak => 2 signals
        rows = [{
            "symbol_code": "000004", "symbol_name": "测", "entry_date": "20260801",
            "entry_price": 10.0, "current_price": 12.0, "highest_price": 12.2,
            "ma20": 10.5, "holding_days": 5,
            "trade_plan": {
                "close_vs_20d_high_pct": -1.5,
                "sector_1d_return": -2.0,
                "relative_strength_20d_pct": 8.0,
                "relative_strength_60d_pct": 12.0,
            },
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "reduce")
        self.assertEqual(d.exit_class, "REDUCE")
        self.assertGreater(d.reduce_pct, 0)

    def test_macd_decay_is_combined_signal_only(self):
        eng = make_engine()
        rows = [{
            "symbol_code": "000004", "symbol_name": "测", "entry_date": "20260801",
            "entry_price": 10.0, "current_price": 11.0, "highest_price": 11.2,
            "ma10": 10.5, "ma20": 9.8, "holding_days": 3,
            "trade_plan": {"macd_hist": -0.12, "macd_hist_delta": -0.03, "macd_hist_declining_3d": True},
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "decay")
        self.assertNotEqual(d.exit_class, "REDUCE")
        self.assertIn("macd_momentum_decay", d.decay_signals)

        rows[0]["trade_plan"]["sector_1d_return"] = -2.0
        d2 = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d2.action, "reduce")
        self.assertIn("macd_momentum_decay", d2.decay_signals)

    def test_extreme_event_sell_now(self):
        eng = make_engine()
        rows = [{
            "symbol_code": "000003", "symbol_name": "测", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 12.0, "highest_price": 12.0,
            "event_catalyst": {"severity": "EXTREME", "catalyst": "NEGATIVE"},
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "sell")
        self.assertEqual(d.exit_class, "SELL_NOW")

    def test_high_volume_extension_holds_not_reduce(self):
        eng = make_engine()
        rows = [{
            "symbol_code": "600888", "symbol_name": "西部黄金", "entry_date": "20260818",
            "entry_price": 28.0, "current_price": 34.08, "highest_price": 34.56,
            "highest_close": 34.56, "ma20": 30.0, "holding_days": 2,
            "trade_plan": {
                "close": 34.08, "ret_5d_pct": 14.5, "ret_20d_pct": 30.0, "volume_ratio": 1.52,
                "sector_1d_return": 3.19, "relative_strength_20d_pct": 12, "relative_strength_60d_pct": 10,
            },
            "realtime_quote": {
                "open": 33.51, "high": 34.56, "low": 33.51, "vwap": 32.71, "vwap_state": "Above",
                "sector_1d_return": 3.19,
            },
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "hold")
        self.assertNotEqual(d.exit_class, "REDUCE")
        self.assertEqual(d.high_volume_class, "extension")
        self.assertIn("强势扩张", d.reason)

    def test_high_volume_rejection_contributes_reduce(self):
        eng = make_engine()
        rows = [{
            "symbol_code": "600999", "symbol_name": "测试分歧", "entry_date": "20260818",
            "entry_price": 20.0, "current_price": 24.0, "highest_price": 25.0,
            "highest_close": 25.0, "ma20": 20.0, "holding_days": 2,
            "trade_plan": {
                "close": 24.0, "ret_5d_pct": 16.0, "ret_20d_pct": 30.0, "volume_ratio": 3.0,
                "sector_1d_return": -2.0, "relative_strength_20d_pct": 8, "relative_strength_60d_pct": 12,
            },
            "realtime_quote": {
                "open": 25.4, "high": 25.8, "low": 23.8, "vwap": 24.5, "vwap_state": "Below",
                "sector_1d_return": -2.0,
            },
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "reduce")
        self.assertEqual(d.high_volume_class, "rejection")



class MainTrendRefreshFactorsTest(unittest.TestCase):
    def test_missing_daily_factor_marks_data_incomplete_watch(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        h = Holding(
            symbol_code="600000", symbol_name="缺数据", entry_date="20260824", entry_price=10.0,
            current_price=10.5, ma10=10.2, ma20=9.8,
            trend_state="S1", trend_state_streak=2, trend_state_as_of="20260824",
        )
        orig_factor = eng._factor_for_row
        eng._factor_for_row = lambda *args, **kwargs: {}  # type: ignore[assignment]
        eng._build_sector_snapshot = lambda trade_date: {}  # type: ignore[assignment]
        try:
            refreshed = eng.refresh_holding_factors([h], trade_date="20260825")
        finally:
            eng._factor_for_row = orig_factor
        self.assertEqual(refreshed[0].trend_state, "S0")
        self.assertEqual(refreshed[0].previous_trend_state, "S1")
        self.assertEqual(refreshed[0].trend_reason_code, "DATA_INCOMPLETE")
        decision = eng.evaluate_exits(refreshed)[0]
        self.assertEqual(decision.position_state, "WATCH")
        self.assertEqual(decision.action, "hold")

    def test_refresh_holding_factors_updates_ma20_and_sector_rs(self):
        """状态更新时用新因子/板块/RS 覆盖旧缓存，StateMachine 才能吃上新因子。"""
        from strategies.main_trend.engine import _enrich_residual_rs
        from utils.sector_enrichment import enrich_factor_with_sector, enrich_factor_with_sector_by_name

        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        fake_factor = {
            "symbol_code": "600111",
            "symbol_name": "测刷新",
            "close": 13.0,
            "open": 12.5,
            "high": 13.5,
            "low": 12.4,
            "ma20": 10.0,
            "prev_ma20": 9.8,
            "volume_ratio": 1.9,
            "relative_strength_20d_pct": 12.0,
            "relative_strength_60d_pct": 15.0,
            "relative_strength_cross_section_pct": 70.0,
            "relative_strength_score": 78.0,
            "close_vs_20d_high_pct": 0.0,
            "breakout_20d": True,
            "breakout_60d": True,
            "atr": 0.4,
            "atr_pct": 3.1,
            "vwap": 12.8,
            "vwap_20": 12.8,
            "ret_5d_pct": 12.0,
            "ret_20d_pct": 30.0,
            "ret_1d_pct": 3.0,
        }
        sector_snapshot = {"600111": {"sector_1d_return": 1.2, "sector_rank": 5}}
        fake_factor = enrich_factor_with_sector(fake_factor, sector_snapshot)
        fake_factor = enrich_factor_with_sector_by_name(fake_factor, {"贵金属": {"sector_1d_return": 1.2, "sector_rank": 5}}, "贵金属")
        fake_factor = _enrich_residual_rs(fake_factor) or fake_factor

        h = Holding(
            symbol_code="600111",
            symbol_name="测刷新",
            entry_date="20260818",
            entry_price=10.0,
            current_price=13.0,
            ma20=8.0,
            prev_ma20=7.8,
            trade_plan={"close": 10.0, "ma20": 8.0, "sector_rank": 90, "relative_strength_score": 30},
            realtime_quote={"vwap": 9.0, "vwap_state": "Below"},
            trend_state="S1",
            trend_state_streak=3,
            trend_state_as_of="20260823",
            trend_state_changed_at="20260821",
        )

        orig_factor = eng._factor_for_row
        eng._factor_for_row = lambda row, start, end, trade_date, benchmark: dict(fake_factor)  # type: ignore[assignment]
        eng._build_sector_snapshot = lambda trade_date: sector_snapshot  # type: ignore[assignment]
        try:
            out = eng.refresh_holding_factors([h], trade_date="20260824")
            first_streak = out[0].trend_state_streak
            out = eng.refresh_holding_factors(out, trade_date="20260824")
        finally:
            eng._factor_for_row = orig_factor

        self.assertEqual(len(out), 1)
        r = out[0]
        tp = r.trade_plan or {}
        rt = r.realtime_quote or {}
        self.assertGreater(tp.get("ma20"), 9.0)
        self.assertGreater(tp.get("sector_rank") or 0, 0)
        self.assertEqual(tp.get("sector_1d_return"), 1.2)
        self.assertGreater(tp.get("relative_strength_cross_section_pct") or 0, 0)
        self.assertNotEqual(tp.get("relative_strength_score"), 0)
        self.assertEqual(rt.get("vwap_state"), "Above")
        self.assertEqual(rt.get("vwap"), 12.8)
        self.assertEqual(r.trend_state_streak, first_streak)
        self.assertEqual(r.trend_state_as_of, "20260824")


class HighVolumeShadowBodyTest(unittest.TestCase):
    def _run(self, close, open_px, high, low, vwap, ret5=16.0, vol_ratio=1.6, sector=2.0):
        rows = [{
            "symbol_code": "600123", "symbol_name": "测试", "entry_date": "20260818",
            "entry_price": 20.0, "current_price": close, "highest_price": high,
            "highest_close": high, "ma20": 18.0, "holding_days": 2,
            "trade_plan": {
                "close": close, "ret_5d_pct": ret5, "ret_20d_pct": 30.0, "volume_ratio": vol_ratio,
                "sector_1d_return": sector, "relative_strength_20d_pct": 10, "relative_strength_60d_pct": 12,
            },
            "realtime_quote": {"open": open_px, "high": high, "low": low, "vwap": vwap, "vwap_state": "Above" if close >= vwap else "Below", "sector_1d_return": sector},
        }]
        eng = make_engine()
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertIsNotNone(d)
        return d

    def test_yangline_short_upper_shadow_is_extension_hold(self):
        # 晓程科技式：阳线+短上影，收盘在振幅上沿，且高于 VWAP -> extension，不让 REDUCE。
        d = self._run(close=58.33, open_px=53.68, high=61.7, low=53.0, vwap=57.04)
        self.assertEqual(d.high_volume_class, "extension")
        self.assertNotEqual(d.exit_class, "REDUCE")
        self.assertEqual(d.action, "hold")

    def test_yinline_long_upper_shadow_is_rejection(self):
        # 康希诺式：阴线 + 长上影（上影>实体1.5倍），且收盘低于 VWAP/收在低区 -> rejection，可 REDUCE。
        d = self._run(close=75.5, open_px=77.0, high=80.0, low=75.0, vwap=77.0, ret5=14.0, vol_ratio=1.8)
        self.assertEqual(d.high_volume_class, "rejection")
        self.assertEqual(d.action, "reduce")

    def test_realtime_quote_overrides_stale_extension_cache(self):
        eng = make_engine()
        rows = [{
            "symbol_code": "601069", "symbol_name": "西部黄金", "entry_date": "20260823",
            "entry_price": 31.89, "current_price": 31.4, "highest_price": 34.56,
            "highest_close": 34.08, "ma20": 27.391, "holding_days": 1,
            "trade_plan": {
                "close": 34.08, "ret_5d_pct": 20.0, "volume_ratio": 1.52,
                "sector_1d_return": 3.19,
            },
            "realtime_quote": {
                "price": 31.4, "open": 33.0, "high": 33.26, "low": 30.68,
                "vwap": 31.7781, "volume_ratio": 1.12, "vwap_state": "Below",
            },
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.high_volume_class, "neutral")
        self.assertNotIn("放量强势扩张", d.reason)


class NextDayGuardTest(unittest.TestCase):
    def test_yesterday_vwap_break_adds_guard_signal(self):
        # 昨日 VWAP 在 trade_plan.next_day_guard_vwap，今日收盘跌破 -> REDUCE 被该信号加持。
        eng = make_engine()
        rows = [{
            "symbol_code": "600321", "symbol_name": "破位警戒", "entry_date": "20260818",
            "entry_price": 20.0, "current_price": 22.85, "highest_price": 25.0,
            "highest_close": 25.0, "ma20": 20.0, "holding_days": 2,
            "trade_plan": {
                "close": 22.85, "ret_5d_pct": 16.0, "ret_20d_pct": 30.0, "volume_ratio": 1.8,
                "sector_1d_return": -0.5, "relative_strength_20d_pct": 10, "relative_strength_60d_pct": 12,
                "next_day_guard_vwap": 23.0,
            },
            "realtime_quote": {"open": 23.0, "high": 23.4, "low": 22.8, "vwap": 23.0, "vwap_state": "Below"},
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertIn("next_day_guard_break_vwap", d.decay_signals)
        self.assertLess(d.current_return_pct, 20.0)

    def test_persist_guard_for_next_trading_day(self):
        # 今天 extension / 收在高位：结束后 trade_plan 应固化 next_day_guard_vwap/high。
        eng = make_engine()
        rows = [{
            "symbol_code": "600322", "symbol_name": "固化警戒", "entry_date": "20260818",
            "entry_price": 28.0, "current_price": 34.08, "highest_price": 34.56,
            "highest_close": 34.56, "ma20": 30.0, "holding_days": 2,
            "trade_plan": {"close": 34.08, "ret_5d_pct": 14.5, "ret_20d_pct": 30.0, "volume_ratio": 1.52, "sector_1d_return": 3.19, "relative_strength_20d_pct": 12, "relative_strength_60d_pct": 10},
            "realtime_quote": {"open": 33.51, "high": 34.56, "low": 33.51, "vwap": 32.71, "vwap_state": "Above", "sector_1d_return": 3.19},
        }]
        h = holdings_from_rows(rows)[0]
        eng.evaluate_exits([h])
        tp = h.trade_plan or {}
        self.assertGreater(tp.get("next_day_guard_vwap") or 0, 32.0)
        self.assertGreater(tp.get("next_day_guard_high") or 0, 34.0)

    def test_intraday_wave_does_not_overwrite_previous_day_guard(self):
        eng = make_engine()
        rows = [{
            "symbol_code": "600323", "symbol_name": "盘中警戒", "entry_date": "20260818",
            "entry_price": 20.0, "current_price": 22.9, "highest_price": 25.0,
            "highest_close": 25.0, "ma20": 20.0, "holding_days": 2,
            "trade_plan": {"next_day_guard_vwap": 23.0, "next_day_guard_high": 25.0},
            "realtime_quote": {"price": 22.9, "high": 23.4, "low": 22.8, "vwap": 22.95},
        }]
        h = holdings_from_rows(rows)[0]
        d = eng.evaluate_exits([h], persist_next_day_guard=False)[0]
        self.assertEqual(h.trade_plan.get("next_day_guard_vwap"), 23.0)
        self.assertEqual(d.next_day_guard_vwap, 23.0)


class ProfitTargetTest(unittest.TestCase):
    def test_profit_protect_is_reference_not_fixed_take_profit(self):
        eng = make_engine()
        rows = [{
            "symbol_code": "600324", "symbol_name": "盈利保护", "entry_date": "20260818",
            "entry_price": 100.0, "current_price": 108.0, "highest_price": 110.0,
            "highest_close": 110.0, "ma10": 104.0, "ma20": 96.0, "holding_days": 2,
            "trade_plan": {
                "target_price_1": 106.0,
                "target_price_2": 110.0,
                "close": 108.0,
                "ret_5d_pct": 9.0,
                "ret_20d_pct": 18.0,
                "volume_ratio": 1.2,
                "relative_strength_20d_pct": 8.0,
                "relative_strength_60d_pct": 10.0,
                "sector_1d_return": 0.5,
            },
            "realtime_quote": {"vwap": 105.0, "vwap_state": "Above"},
        }]
        h = holdings_from_rows(rows)[0]
        d = eng.evaluate_exits([h])[0]
        self.assertEqual(d.target_price_1, 106.0)
        self.assertEqual(d.target_price_2, 110.0)
        self.assertEqual(d.profit_protect_price, 104.0)
        self.assertEqual(d.profit_protect_level, "lock_4pct")
        self.assertFalse(d.take_profit_triggered)

if __name__ == "__main__":
    unittest.main()

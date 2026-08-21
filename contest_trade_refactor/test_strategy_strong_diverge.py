"""Tests for the independent Strong Diverge strategy package."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.strategies import get_strategy, get_strategies
from strategies.strong_diverge.engine import StrongDivergeConfig, StrongDivergeEngine
from strategies.strong_diverge.schemas import Holding, WatchlistItem, WatchlistPool


def _sample_factor(change_pct: float = -2.0, board: int = 3) -> dict:
    return {
        "symbol_code": "600001.SH",
        "symbol_name": "测试",
        "open": 10.0,
        "close": 10.2,
        "high": 10.5,
        "low": 9.95,
        "vwap_20": 10.1,
        "vwap": 10.1,
        "change_pct": change_pct,
        "close_above_ma5": True,
        "ma5_slope_pct": 0.5,
        "volume_ratio": 0.6,
        "amount_ratio": 0.7,
        "daily_entry_score": 60,
        "weekly_trend_score": 70,
        "relative_strength_score": 65,
        "breakout_20d": True,
        "ma20_deviation_pct": 5.0,
        "close_vs_20d_high_pct": -1.5,
        "seal_strength": 8.0,
        "continuous_board": board,
        "data_quality_valid": True,
        "data_quality_status": "ok",
    }


def _sample_watch_item():
    factor = _sample_factor(change_pct=-2.0, board=3)
    return WatchlistItem(
        symbol_code="600001.SH",
        symbol_name="测试",
        trade_date="20260818",
        pool_type="连板",
        strong_tags=["连板"],
        strength_watch_score=82.0,
        setup_score=70.0,
        strong_structure={"board_count": 3, "break_count": 0, "seal_strength": 8.0},
        factors=[factor],
    )


def _single_pool(item):
    return WatchlistPool(lian=[item], all_items=[item])


class StrongDivergePackageTest(unittest.TestCase):
    def test_package_registered(self):
        ids = [s.get("id") for s in get_strategies()]
        self.assertIn("strong_diverge", ids)
        cfg = get_strategy("strong_diverge")
        self.assertEqual(cfg.get("id"), "strong_diverge")
        self.assertIn("discovery", cfg)
        self.assertIn("divergence", cfg)
        self.assertIn("backtest", cfg)
        self.assertTrue(cfg.get("belief_list"))

    def test_from_yaml(self):
        cfg = StrongDivergeConfig.from_yaml()
        self.assertEqual(cfg.id, "strong_diverge")
        self.assertIn("max_lianban", cfg.watchlist)
        self.assertIn("min_score", cfg.divergence)
        self.assertIn("min_limit_up_count", cfg.market)

    def test_exit_stop_loss_price_unconditional(self):
        engine = StrongDivergeEngine(StrongDivergeConfig.from_yaml())
        h = Holding("600001.SH", "测试", "2026-08-17", 10.0,
                    current_price=9.8, highest_price=10.5, holding_days=1,
                    stop_loss_price=9.9)
        result = engine.evaluate_exits([h])[0]
        self.assertEqual(result.action, "sell")
        self.assertTrue(result.stop_loss_triggered)
        self.assertIn("跌破初始止损位", result.reason)

    def test_detect_shouyin(self):
        engine = StrongDivergeEngine(StrongDivergeConfig.from_yaml())
        signal = engine.detect_divergence(_single_pool(_sample_watch_item()), "20260818")
        self.assertEqual(len(signal), 1)
        self.assertEqual(signal[0].divergence_mode, "首阴")
        self.assertTrue(signal[0].divergence_pass)

    def test_confirmed_first_divergence_cannot_buy_without_gate(self):
        engine = StrongDivergeEngine(StrongDivergeConfig.from_yaml())
        item = _sample_watch_item()
        pool = _single_pool(item)
        divs = engine.detect_divergence(pool, "20260818")
        self.assertTrue(divs[0].divergence_event)
        self.assertTrue(divs[0].divergence_pass)
        confirmed = engine.confirm_buy(divs)
        buys = engine.build_t1_buy_plan(confirmed)
        # 新设计：分歧当天不能直接买，必须经过 weak_to_strong Gate
        self.assertFalse(any(b.buy_ready for b in buys))
        self.assertFalse(item.weak_to_strong_confirmed)

    def test_exit_sell(self):
        engine = StrongDivergeEngine(StrongDivergeConfig.from_yaml())
        h = Holding("600001.SH", "测试", "2026-08-17", 10.0,
                    current_price=9.4, highest_price=10.5, holding_days=2)
        result = engine.evaluate_exits([h])
        self.assertEqual(result[0].action, "sell")
        self.assertTrue(result[0].stop_loss_triggered)

    def test_exit_reduce_on_drawdown_before_hard_stop(self):
        engine = StrongDivergeEngine(StrongDivergeConfig.from_yaml())
        h = Holding("600001.SH", "测试", "2026-08-17", 10.0,
                    current_price=9.7, highest_price=10.5, holding_days=2)
        result = engine.evaluate_exits([h])
        self.assertEqual(result[0].action, "reduce")
        self.assertTrue(result[0].reduce_triggered)

    def test_exit_hold(self):
        engine = StrongDivergeEngine(StrongDivergeConfig.from_yaml())
        h = Holding("600001.SH", "测试", "2026-08-17", 10.0,
                    current_price=10.5, highest_price=10.8, holding_days=1)
        result = engine.evaluate_exits([h])
        self.assertEqual(result[0].action, "hold")


class StrongDivergePoolTest(unittest.TestCase):
    def test_pool_type_split(self):
        engine = StrongDivergeEngine(StrongDivergeConfig.from_yaml())
        base = {
            'symbol_code': '600002.SH', 'symbol_name': '测试', 'data_quality_valid': True,
            'data_quality_status': 'ok', 'ma20_deviation_pct': 5, 'close_above_ma5': True,
            'volume_ratio': 1.3, 'amount_ratio': 1.2, 'change_pct': -2.0, 'daily_entry_score': 60,
        }
        lian_factor = dict(base)
        lian_factor.update({'weekly_trend_score':60,'relative_strength_score':65,'breakout_20d':True,'seal_strength':8.0,'continuous_board':3})
        lian_zt = {'600002.SH': {'continuous_board':3,'break_count':0,'seal_strength':8.0,'one_word_limit_up':False}}
        tupo_factor = dict(base)
        tupo_factor.update({'breakout_20d': True, 'breakout_60d': True, 'close_vs_20d_high_pct': 1.0, 'close_vs_60d_high_pct': 1.0})
        trend_factor = dict(base)
        trend_factor.update({'weekly_trend_score':62,'relative_strength_score':55,'breakout_60d':False})

        lian = engine._classify_candidate(lian_factor, lian_zt)
        tupo = engine._classify_candidate(tupo_factor, {})
        trend = engine._classify_candidate(trend_factor, {})
        self.assertEqual(lian.pool_type, "连板")
        self.assertEqual(tupo.pool_type, "突破")
        self.assertEqual(trend.pool_type, "趋势")
        self.assertGreater(lian.strength_watch_score, tupo.strength_watch_score)
        self.assertGreater(tupo.strength_watch_score, trend.strength_watch_score)

class StrongDivergeStateMachineTest(unittest.TestCase):
    def _engine(self):
        return StrongDivergeEngine(StrongDivergeConfig.from_yaml())

    def _factor(self, change_pct=None, close_above_ma5=True, ma5_slope_pct=0.5, volume_ratio=1.2):
        f = _sample_factor(change_pct=change_pct if change_pct is not None else 2.0, board=2)
        f.update({
            "close_above_ma5": close_above_ma5,
            "ma5_slope_pct": ma5_slope_pct,
            "volume_ratio": volume_ratio,
            "hh_strict": True,
            "hl_strict": True,
            "hh_hl_strict": True,
            "pullback_near_vwap": True,
            "pullback_shrink": volume_ratio < 1.0,
            "rising_volume": volume_ratio >= 1.0 and (change_pct or 0) > 0,
            "low": f["low"],
        })
        return f

    def test_diverge_day_marks_first_but_no_buy(self):
        engine = self._engine()
        f = self._factor(change_pct=-1.5)
        item = _sample_watch_item()
        item.factors = [f]
        pool = _single_pool(item)
        engine.detect_divergence(pool, "20260818")
        engine.advance_lifecycle_states(pool, "20260818")
        self.assertEqual(item.state, "首次")
        self.assertEqual(item.divergence_dates, ["20260818"])
        raw = engine.apply_state_machine(pool, "20260818")
        self.assertEqual(raw, [])

    def test_confirm_next_day_enables_buy(self):
        engine = self._engine()
        f_div = self._factor(change_pct=-1.5)
        item = _sample_watch_item()
        item.factors = [f_div]
        pool = _single_pool(item)
        engine.detect_divergence(pool, "20260818")
        engine.advance_lifecycle_states(pool, "20260818")
        self.assertEqual(item.state, "首次")
        self.assertTrue(item.divergence_event)
        self.assertFalse(item.weak_to_strong_confirmed)

        f_conf = self._factor(change_pct=2.0, close_above_ma5=True, ma5_slope_pct=0.6, volume_ratio=1.1)
        item.factors.append(f_conf)
        engine.advance_lifecycle_states(pool, "20260819")
        self.assertIn("confirmation_dates", item.to_dict())
        self.assertTrue(item.weak_to_strong_confirmed)
        self.assertGreaterEqual(item.weak_to_strong_gate_detail.get("passed_count", 0), 4)

        f_ready = self._factor(change_pct=3.0, close_above_ma5=True, ma5_slope_pct=0.8, volume_ratio=1.3)
        item.factors.append(f_ready)
        engine.advance_lifecycle_states(pool, "20260820")
        raw = engine.apply_state_machine(pool, "20260820")
        self.assertTrue(any(r["buy_ready"] for r in raw))

    def test_no_buy_when_weak_gate_fails_even_if_score_high(self):
        engine = self._engine()
        f = self._factor(change_pct=3.0, close_above_ma5=True, ma5_slope_pct=0.8, volume_ratio=1.3)
        item = _sample_watch_item()
        item.factors = [f]
        item.weak_to_strong_confirmed = False
        pool = _single_pool(item)
        raw = engine.apply_state_machine(pool, "20260820")
        self.assertEqual(raw, [])


class StrongDivergeStrictDivergenceTest(unittest.TestCase):
    def _engine(self):
        return StrongDivergeEngine(StrongDivergeConfig.from_yaml())

    def test_negative_day_without_prior_strength_is_not_divergence_event(self):
        engine = self._engine()
        item = _sample_watch_item()
        item.strong_structure = {"board_count": 0, "break_count": 0, "seal_strength": 0.0}
        item.pool_type = "突破"
        item.last_board_date = ""
        f = _sample_factor(change_pct=-2.0, board=0)
        f.update({"low": 9.0, "close": 9.0, "open": 9.2, "vwap": 9.1})
        item.factors = [f]
        pool = _single_pool(item)
        divs = engine.detect_divergence(pool, "20260818")
        self.assertFalse(divs[0].divergence_event)

    def test_first_non_board_after_strength_with_positive_rise_is_divergence(self):
        engine = self._engine()
        item = _sample_watch_item()
        f = _sample_factor(change_pct=5.0, board=0)
        f.update({"continuous_board": 0, "low": 10.0, "close": 10.4, "vwap": 10.1, "open": 10.05})
        item.factors = [f]
        item.strong_structure = {"board_count": 3, "break_count": 0, "seal_strength": 8.0}
        pool = _single_pool(item)
        divs = engine.detect_divergence(pool, "20260818")
        self.assertTrue(divs[0].divergence_event)
        self.assertEqual(divs[0].divergence_mode, "断板")
        self.assertTrue(divs[0].divergence_pass)


class StrongDiverge20cmAndAliasTest(unittest.TestCase):
    def _engine(self):
        return StrongDivergeEngine(StrongDivergeConfig.from_yaml())

    def test_gem_plus_10_is_not_limit_up_non_board_event(self):
        engine = self._engine()
        item = _sample_watch_item()
        item.symbol_code = "300001.SZ"
        item.pool_type = "连板"
        item.strong_structure = {"board_count": 3, "break_count": 0, "seal_strength": 8.0}
        f = _sample_factor(change_pct=10.0, board=0)
        f.update({"symbol_code": "300001.SZ", "continuous_board": 0, "close": 10.3, "vwap": 10.1, "open": 10.05, "low": 10.0})
        item.factors = [f]
        pool = _single_pool(item)
        divs = engine.detect_divergence(pool, "20260818")
        self.assertTrue(divs[0].divergence_event)
        self.assertEqual(divs[0].divergence_mode, "断板")

    def test_first_negative_date_alias(self):
        item = _sample_watch_item()
        item.first_negative_date = "20260818"
        self.assertEqual(item.first_negative_after_strength, "20260818")
        item.first_negative_after_strength = "20260819"
        self.assertEqual(item.first_negative_date, "20260819")


class StrongDivergeBreakGradeTest(unittest.TestCase):
    def _engine(self):
        return StrongDivergeEngine(StrongDivergeConfig.from_yaml())

    def _item_for_break(self, change_pct, vol=1.0, close_above_ma5=True):
        item = _sample_watch_item()
        item.strong_structure = {"board_count": 3, "break_count": 0, "seal_strength": 8.0}
        f = _sample_factor(change_pct=change_pct, board=0)
        f.update({"continuous_board": 0, "low": 10.0, "close": 10.4, "vwap": 10.1, "open": 10.05, "volume_ratio": vol, "close_above_ma5": close_above_ma5})
        item.factors = [f]
        return item, _single_pool(item)

    def test_break_A_healthy_positive_shrink_close_high(self):
        engine = self._engine()
        item, pool = self._item_for_break(5.0, vol=0.6, close_above_ma5=True)
        sig = engine.detect_divergence(pool, "20260818")[0]
        self.assertTrue(sig.divergence_event)
        self.assertEqual(sig.divergence_mode, "断板")
        self.assertEqual(sig.divergence_grade, "A")
        self.assertEqual(sig.divergence_class, "健康分歧")

    def test_break_B_neutral_small_change_normal_volume(self):
        engine = self._engine()
        item, pool = self._item_for_break(0.5, vol=1.1, close_above_ma5=True)
        sig = engine.detect_divergence(pool, "20260818")[0]
        self.assertTrue(sig.divergence_event)
        self.assertEqual(sig.divergence_grade, "B")
        self.assertEqual(sig.divergence_class, "中性分歧")

    def test_break_C_weak_big_down_high_volume_broken_key(self):
        engine = self._engine()
        item, pool = self._item_for_break(-5.0, vol=2.2, close_above_ma5=False)
        sig = engine.detect_divergence(pool, "20260818")[0]
        self.assertTrue(sig.divergence_event)
        self.assertEqual(sig.divergence_grade, "C")
        self.assertEqual(sig.divergence_class, "弱分歧")

    def test_positive_duanban_without_failed_board_still_event_for_watch(self):
        engine = self._engine()
        item, pool = self._item_for_break(5.0, vol=0.6)
        sig = engine.detect_divergence(pool, "20260818")[0]
        self.assertTrue(sig.divergence_event)
        self.assertTrue(sig.divergence_pass)


class StrongDivergeStrictGateTest(unittest.TestCase):
    def _engine(self):
        return StrongDivergeEngine(StrongDivergeConfig.from_yaml())

    def _item(self, factor_extra=None, has_divergence=True):
        item = _sample_watch_item()
        f = _sample_factor(change_pct=2.0, board=3)
        f.update({
            "close_above_ma5": True,
            "ma5_slope_pct": 0.6,
            "volume_ratio": 1.3,
            "open": 10.0,
            "close": 10.4,
            "low": 10.05,
            "vwap": 10.1,
            "hh_strict": True,
            "hl_strict": True,
            "hh_hl_strict": True,
            "pullback_near_vwap": True,
            "pullback_shrink": False,
            "rising_volume": True,
        })
        if factor_extra:
            f.update(factor_extra)
        item.factors = [f]
        if has_divergence:
            item.state = "首次"
            item.divergence_dates = ["20260818"]
            item.divergence_event = True
        return item, _single_pool(item)

    def test_weak_to_strong_gate_all_5_passes(self):
        engine = self._engine()
        item, pool = self._item()
        gate = engine._check_weak_to_strong_gates(item, "20260819")
        self.assertGreaterEqual(gate["passed_count"], 4)
        self.assertTrue(gate["confirmed"])
        self.assertTrue(gate["gates"].get("站上开盘价"))
        self.assertTrue(gate["gates"].get("站上VWAP"))
        self.assertTrue(gate["gates"].get("回踩VWAP成功"))
        self.assertTrue(gate["gates"].get("HH/HL短线结构"))
        self.assertTrue(gate["gates"].get("量价健康"))

    def test_weak_to_strong_gate_fails_without_hh_hl_and_pullback(self):
        engine = self._engine()
        item, pool = self._item(factor_extra={
            "hh_strict": False,
            "hl_strict": False,
            "hh_hl_strict": False,
            "pullback_near_vwap": False,
            "low": 10.6,  # 没有回踩
            "vwap": 10.1,
            "close": 10.4,
        })
        gate = engine._check_weak_to_strong_gates(item, "20260819")
        self.assertLess(gate["passed_count"], 4)
        self.assertFalse(gate["confirmed"])

class StrongDivergeFirstBoardContinuationTest(unittest.TestCase):
    def _engine(self):
        return StrongDivergeEngine(StrongDivergeConfig.from_yaml())

    def _fb_item(self, factor_extra=None, state_marker=True):
        item = _sample_watch_item()
        item.pool_type = "连板"
        item.strong_tags = ["连板", "首板"]
        item.strong_structure = {"board_count": 1, "break_count": 0, "seal_strength": 9.0}
        item.limit_snapshot = {"seal_strength": 9.0, "continuous_board": 1, "break_count": 0}
        f = _sample_factor(change_pct=10.0, board=1)
        f.update({
            "continuous_board": 1,
            "symbol_code": "600001.SH",
            "close": 11.0,
            "vwap_20": 10.5,
            "vwap": 10.5,
            "low": 10.2,
            "volume_ratio": 1.5,
            "amount_ratio": 1.5,
            "ret_3d_pct": 2.0,
            "ret_5d_pct": 3.0,
            "close_vs_20d_high_pct": 2.0,
        })
        if factor_extra:
            f.update(factor_extra)
        item.factors = [f]
        if state_marker:
            item.first_board_event = True
            item.first_board_date = "20260818"
            item.first_board_close = 11.0
            item.first_board_prev_not_board_date = "20260817"
        return item, _single_pool(item)

    def test_refresh_marks_first_board_from_series(self):
        engine = self._engine()
        item = WatchlistItem(
            symbol_code="600001.SH", symbol_name="测试", trade_date="20260819",
            pool_type="连板", strong_tags=["首板"],
            factors=[
                {"report_date": "20260818", "change_pct": 10.0, "close": 11.0, "continuous_board": 1},
                {"report_date": "20260817", "change_pct": -1.0, "close": 10.0, "continuous_board": 0},
            ],
        )
        pool = _single_pool(item)
        engine.refresh_lifecycle_metadata(pool)
        self.assertTrue(item.first_board_event)
        self.assertEqual(item.first_board_date, "20260818")
        self.assertAlmostEqual(item.first_board_close or 0, 11.0)

    def test_first_board_quality_pass(self):
        engine = self._engine()
        item, pool = self._fb_item()
        engine.detect_first_board(pool, "20260818")
        self.assertGreaterEqual(item.first_board_quality_score, 60)
        self.assertIn(item.first_board_quality_grade, {"A", "B"})

    def test_continuation_gate_passes_next_day(self):
        engine = self._engine()
        item, pool = self._fb_item()
        engine.refresh_lifecycle_metadata(pool)
        cont_factor = dict(pool.all_items[0].factors[0])
        cont_factor.update({
            "report_date": "20260819",
            "change_pct": 2.0,
            "open": 10.8,
            "close": 11.5,
            "volume_ratio": 1.2,
            "low": 10.8,
            "vwap": 10.5,
            "close_above_ma5": True,
            "continuous_board": 0,
        })
        item.factors.append(cont_factor)
        engine.advance_first_board_state(pool, "20260819")
        self.assertTrue(item.first_board_continuation_confirmed)
        self.assertGreaterEqual(item.first_board_continuation_score, 60)

    def test_first_board_buy_ready_only_after_continuation(self):
        engine = self._engine()
        item, pool = self._fb_item()
        engine.detect_first_board(pool, "20260818")
        self.assertFalse(any(r["buy_ready"] for r in engine.apply_first_board_state_machine(pool, "20260818")))
        cont_factor = dict(item.latest_factor())
        cont_factor.update({
            "report_date": "20260819",
            "change_pct": 2.0,
            "open": 10.6,
            "close": 11.2,
            "volume_ratio": 1.2,
            "low": 10.9,
            "vwap": 10.5,
            "close_above_ma5": True,
            "continuous_board": 0,
        })
        item.factors.append(cont_factor)
        engine.advance_first_board_state(pool, "20260819")
        rows = engine.apply_first_board_state_machine(pool, "20260819")
        self.assertTrue(any(r["buy_ready"] for r in rows))

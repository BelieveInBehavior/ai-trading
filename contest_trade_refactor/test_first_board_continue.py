"""Tests for the independent first_board_continue strategy package."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.strategies import get_strategy, get_strategies
from strategies.first_board_continue.engine import FirstBoardContinueConfig, FirstBoardContinueEngine
from strategies.first_board_continue.schemas import WatchlistItem


def _fb_factor(change_pct: float = 10.0, date: str = "20260818"):
    return {
        "report_date": date,
        "symbol_code": "600001.SH",
        "symbol_name": "测试",
        "change_pct": change_pct,
        "close": 11.0,
        "open": 10.1,
        "high": 11.1,
        "low": 10.2,
        "volume_ratio": 1.5,
        "amount_ratio": 1.5,
        "vwap_20": 10.5,
        "vwap": 10.5,
        "close_above_ma5": True,
        "ret_3d_pct": 2.0,
        "ret_5d_pct": 3.0,
        "close_vs_20d_high_pct": 2.0,
        "continuous_board": 1,
        "ma20_deviation_pct": 5.0,
        "seal_strength": 9.0,
        "break_count": 0,
    }


def _cont_factor():
    return {
        "report_date": "20260819",
        "symbol_code": "600001.SH",
        "symbol_name": "测试",
        "change_pct": 2.0,
        "close": 11.2,
        "open": 10.6,
        "high": 11.4,
        "low": 10.8,
        "volume_ratio": 1.2,
        "amount_ratio": 1.2,
        "vwap_20": 10.5,
        "vwap": 10.5,
        "close_above_ma5": True,
        "ret_3d_pct": 3.0,
        "close_vs_20d_high_pct": 2.0,
        "continuous_board": 0,
        "ma20_deviation_pct": 5.0,
    }


class FirstBoardContinuePackageTest(unittest.TestCase):
    def test_package_registered(self):
        ids = [s.get("id") for s in get_strategies()]
        self.assertIn("first_board_continue", ids)
        cfg = get_strategy("first_board_continue")
        self.assertEqual(cfg.get("id"), "first_board_continue")
        self.assertIn("first_board", cfg)
        self.assertIn("confirmation", cfg)

    def test_config_from_yaml(self):
        cfg = FirstBoardContinueConfig.from_yaml()
        self.assertEqual(cfg.id, "first_board_continue")
        self.assertEqual(float(cfg.confirmation.get("min_continuation_score", 60)), 60)

    def test_assess_first_board(self):
        eng = FirstBoardContinueEngine(FirstBoardContinueConfig.from_yaml())
        cand = eng._assess_first_board(_fb_factor())
        self.assertIsNotNone(cand)
        self.assertTrue(cand.first_board_event)
        self.assertGreaterEqual(cand.first_board_quality_score, 60)

    def test_detect_first_board_from_series(self):
        eng = FirstBoardContinueEngine(FirstBoardContinueConfig.from_yaml())
        item = WatchlistItem("600001.SH", "测试", "20260818")
        prev = _fb_factor(change_pct=-1.0, date="20260817")
        prev["continuous_board"] = 0
        item.factors = [prev, _fb_factor(change_pct=10.0, date="20260818")]
        eng.detect_first_board([item], "20260818")
        self.assertTrue(item.first_board_event)
        self.assertEqual(item.first_board_date, "20260818")
        self.assertGreaterEqual(item.first_board_quality_score, 60)

    def test_continuation_buy_ready_next_day(self):
        eng = FirstBoardContinueEngine(FirstBoardContinueConfig.from_yaml())
        item = WatchlistItem("600001.SH", "测试", "20260818")
        item.factors = [_fb_factor(date="20260818")]
        eng.detect_first_board([item], "20260818")
        item.factors.append(_cont_factor())
        eng.advance_first_board_state([item], "20260819")
        signals = eng.build_buy_signals([item], "20260819")
        self.assertTrue(any(s.buy_ready for s in signals))


if __name__ == "__main__":
    unittest.main()

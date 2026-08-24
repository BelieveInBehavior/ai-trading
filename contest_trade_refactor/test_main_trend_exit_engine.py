"""Tests for the V1 main_trend Exit state machine (P0-P4), supporting CLI-style holdings."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
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
            ma20=float(r.get("ma20") or 0) if r.get("ma20") not in (None, 0, "") else None,
            prev_close=float(r.get("prev_close") or 0) if r.get("prev_close") not in (None, 0, "") else None,
            prev_ma20=float(r.get("prev_ma20") or 0) if r.get("prev_ma20") not in (None, 0, "") else None,
            atr_trailing_stop=float(r.get("atr_trailing_stop") or 0) if r.get("atr_trailing_stop") not in (None, 0, "") else None,
            trade_plan=r.get("trade_plan") or {},
            realtime_quote=r.get("realtime_quote") or {},
            event_catalyst=r.get("event_catalyst"),
            stop_loss_price=float(r.get("stop_loss_price") or 0) if r.get("stop_loss_price") not in (None, 0, "") else None,
        ))
    return out


class MainTrendExitStateMachineTest(unittest.TestCase):
    def test_ma20_first_day_below_is_warning_not_sell(self):
        eng = make_engine()
        rows = [{
            "symbol_code": "000001", "symbol_name": "测", "entry_date": "20260818",
            "entry_price": 10.0, "current_price": 9.5, "highest_price": 9.55,
            "highest_close": 9.55, "ma20": 9.8, "prev_close": 10.0, "prev_ma20": 9.7,
        }]
        d = eng.evaluate_exits(holdings_from_rows(rows))[0]
        self.assertEqual(d.action, "hold")
        self.assertIn("WARNING", d.reason)

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


if __name__ == "__main__":
    unittest.main()

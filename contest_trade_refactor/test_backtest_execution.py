import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts.backtest_signal_closed_loop import compute_forward_returns, load_all_signals
from scripts.portfolio_simulator import SimConfig, simulate_signals


class TestClosedLoopEvaluation(unittest.TestCase):
    def test_entry_session_close_is_t1(self):
        dates = ["20260803", "20260804", "20260805", "20260806", "20260807"]
        rows = {
            d: {"open": 100 if i == 0 else 100 + i, "close": 101 + i, "high": 102 + i, "low": 99}
            for i, d in enumerate(dates)
        }
        result = compute_forward_returns(rows, dates[0], dates)
        self.assertEqual(result["exit_t1_date"], "20260803")
        self.assertEqual(result["t1_return_pct"], 1.0)
        self.assertEqual(result["t3_return_pct"], 3.0)

    def test_same_symbol_across_groups_is_deduplicated(self):
        payload = {
            "trigger_time": "2026-08-03 18:00:00",
            "buy_signals": [{"symbol_code": "600001.SH", "buy_score": 70}],
            "watchlist": [{"symbol_code": "600001.SH", "buy_score": 65}],
            "research_signals": [{"symbol_code": "600001.SH"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decision.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            records = load_all_signals(str(path))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["__group"], "buy_passed")
        self.assertEqual(set(records[0]["source_groups"]), {"buy_passed", "watch", "research"})


class TestPortfolioExecution(unittest.TestCase):
    def _signals(self, count=1):
        return pd.DataFrame([
            {
                "trigger_time": "2026-08-02 18:00:00",
                "trigger_date": "20260802",
                "entry_date": "20260803",
                "entry_price": 100,
                "symbol_code": f"60000{i}",
                "signal_group": "buy_passed",
                "signal_tier": "A",
                "recommended_position_size_pct": 60,
            }
            for i in range(1, count + 1)
        ])

    @staticmethod
    def _price_map(limit_open=False):
        return {
            "20260802": {"收盘": 100},
            "20260803": {"开盘": 110 if limit_open else 100, "最高": 109, "最低": 94, "收盘": 96},
            "20260804": {"开盘": 94, "最高": 101, "最低": 93, "收盘": 95},
            "20260805": {"开盘": 96, "最高": 102, "最低": 95, "收盘": 101},
        }

    @patch("scripts.portfolio_simulator.get_next_trade_dates", return_value=["20260804", "20260805"])
    @patch("scripts.portfolio_simulator.get_price_map")
    def test_t1_rule_prevents_entry_day_stop(self, get_prices, _dates):
        get_prices.return_value = self._price_map()
        trades = simulate_signals(self._signals(), SimConfig(max_position_pct=60))
        self.assertEqual(trades.iloc[0]["exit_date"], "20260804")
        self.assertEqual(trades.iloc[0]["exit_price"], 94)

    @patch("scripts.portfolio_simulator.get_next_trade_dates", return_value=["20260804", "20260805"])
    @patch("scripts.portfolio_simulator.get_price_map")
    def test_limit_up_open_is_not_filled(self, get_prices, _dates):
        get_prices.return_value = self._price_map(limit_open=True)
        trades = simulate_signals(self._signals(), SimConfig())
        self.assertTrue(trades.empty)

    @patch("scripts.portfolio_simulator.get_next_trade_dates", return_value=["20260804", "20260805"])
    @patch("scripts.portfolio_simulator.get_price_map")
    def test_cash_constraint_blocks_overallocation(self, get_prices, _dates):
        get_prices.return_value = self._price_map()
        trades = simulate_signals(
            self._signals(count=2),
            SimConfig(initial_cash=100_000, max_position_pct=60, min_fill_ratio=0.9),
        )
        self.assertEqual(len(trades), 1)

    def test_holding_period_cannot_violate_t1(self):
        with self.assertRaises(ValueError):
            simulate_signals(self._signals(), SimConfig(holding_days=1))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import pandas as pd

from scripts.main_trend_vectorbt_research import (
    ResearchParams,
    build_param_grid,
    enrich_indicators,
    simulate_symbol_events,
    simulate_symbol,
    summarize_trades,
)


class MainTrendVectorbtResearchTest(unittest.TestCase):
    def _frame(self) -> pd.DataFrame:
        rows = []
        price = 10.0
        for i in range(90):
            if i < 65:
                price *= 1.006
            elif i < 75:
                price *= 0.995
            else:
                price *= 1.004
            rows.append(
                {
                    "date": f"202606{i + 1:02d}",
                    "open": round(price * 0.998, 4),
                    "high": round(price * 1.01, 4),
                    "low": round(price * 0.99, 4),
                    "close": round(price, 4),
                }
            )
        return pd.DataFrame(rows)

    def test_param_grid_filters_invalid_ma_order(self):
        class Args:
            ma_modes = "ema"
            fast_mas = "10,20"
            mid_mas = "20"
            long_mas = "60"
            atr_mults = "2.0"
            max_holding_days = "5"
            max_fast_ma_deviation_pcts = "12"
            test_macd = True
            test_fast_ma_reduce = False
            test_mid_ma_exit = False
            test_atr_trailing = False

        grid = build_param_grid(Args())
        self.assertTrue(grid)
        self.assertTrue(all(p.fast_ma < p.mid_ma < p.long_ma for p in grid))
        self.assertEqual({p.use_macd for p in grid}, {False, True})

    def test_simulation_outputs_summary(self):
        p = ResearchParams(
            ma_mode="ema",
            fast_ma=10,
            mid_ma=20,
            long_ma=60,
            use_macd=False,
            use_fast_ma_reduce=True,
            use_mid_ma_exit=True,
            use_atr_trailing=True,
            atr_mult=2.0,
            max_holding_days=5,
            max_fast_ma_deviation_pct=12.0,
        )
        enriched = enrich_indicators(self._frame(), p)
        self.assertIn("ma_fast", enriched.columns)
        self.assertIn("macd_hist", enriched.columns)

        trades = simulate_symbol("600000", "测试", self._frame(), p, "20260601", "20260690")
        summary = summarize_trades(trades, p, "pandas_event")
        self.assertEqual(summary["param_key"], p.key)
        self.assertEqual(summary["trade_count"], len(trades))
        if trades:
            self.assertIsNotNone(summary["avg_trade_return_pct"])

    def test_event_simulation_uses_supplied_signal_dates(self):
        p = ResearchParams(
            ma_mode="ema",
            fast_ma=10,
            mid_ma=20,
            long_ma=60,
            use_macd=False,
            use_fast_ma_reduce=True,
            use_mid_ma_exit=True,
            use_atr_trailing=False,
            atr_mult=2.0,
            max_holding_days=5,
            max_fast_ma_deviation_pct=12.0,
        )
        frame = self._frame()
        all_trades = simulate_symbol("600000", "测试", frame, p, "20260601", "20260690")
        if not all_trades:
            self.skipTest("synthetic series produced no entry signal")
        signal_date = all_trades[0]["signal_date"]
        event_trades = simulate_symbol_events("600000", "测试", frame, [signal_date], p, "20260601", "20260690")
        self.assertEqual(len(event_trades), 1)
        self.assertEqual(event_trades[0]["signal_date"], signal_date)

        no_event_trades = simulate_symbol_events("600000", "测试", frame, ["20260601"], p, "20260601", "20260690")
        self.assertEqual(no_event_trades, [])


if __name__ == "__main__":
    unittest.main()

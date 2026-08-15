import asyncio
import unittest
from unittest.mock import patch

import pandas as pd

from agents.quantitative_universe_screener import (
    QuantitativeScreenerConfig,
    QuantitativeUniverseScreener,
)
from main_loop import SimpleTradeCompany


def _history_frame(close_values):
    dates = pd.date_range("2025-07-01", periods=len(close_values), freq="D")
    return pd.DataFrame(
        {
            "日期": dates.strftime("%Y-%m-%d"),
            "开盘": close_values,
            "收盘": close_values,
            "最高": [value + 1 for value in close_values],
            "最低": [value - 1 for value in close_values],
            "成交量": [1000000] * len(close_values),
            "涨跌幅": [0.2] * len(close_values),
        }
    )


class TestQuantitativeUniverseScreener(unittest.TestCase):
    def test_screen_filters_full_universe_before_research(self):
        spot_df = pd.DataFrame(
            [
                {"代码": "600001", "名称": "强势股", "成交额": 100000000},
                {"代码": "000001", "名称": "弱势股", "成交额": 90000000},
            ]
        )
        benchmark_df = pd.DataFrame(
            {
                "date": pd.date_range("2025-07-01", periods=260, freq="D").strftime("%Y-%m-%d"),
                "close": [100 + i * 0.1 for i in range(260)],
            }
        )
        histories = {
            "600001": _history_frame([100 + i * 0.5 for i in range(260)]),
            "000001": _history_frame([100 + i * 0.05 for i in range(260)]),
        }

        def fake_run(func_name, func_kwargs, verbose=False):
            if func_name == "stock_zh_a_spot_em":
                return spot_df
            if func_name == "stock_zh_index_daily":
                return benchmark_df
            if func_name == "stock_zh_a_hist":
                return histories[func_kwargs["symbol"]]
            raise AssertionError(f"unexpected func_name: {func_name}")

        screener = QuantitativeUniverseScreener(
            QuantitativeScreenerConfig(
                max_symbols=0,
                max_concurrency=2,
                top_k=10,
                min_weekly_trend_score=55,
                min_relative_strength_score=50,
                min_relative_strength_20d_pct=0,
                min_daily_entry_score=50,
            )
        )
        with patch(
            "agents.quantitative_universe_screener.akshare_cached.run",
            side_effect=fake_run,
        ):
            result = asyncio.run(screener.screen("2026-08-11 10:00:00"))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["universe_count"], 2)
        # V2: 强势股必须通过，弱势股允许进入研究池，但分数必须明显更低。
        self.assertGreaterEqual(result["passed_count"], 1)
        self.assertEqual(result["candidates"][0]["symbol_code"], "600001.SH")
        self.assertGreater(
            result["candidates"][0]["quantitative_score"],
            result["candidates"][-1]["quantitative_score"],
        )
        self.assertIn("允许 Research Agent 研究的候选", result["context_string"])

    def test_research_signals_are_restricted_to_quantitative_candidates(self):
        company = SimpleTradeCompany.__new__(SimpleTradeCompany)
        company.quantitative_screener = QuantitativeUniverseScreener(
            QuantitativeScreenerConfig(enabled=True)
        )
        company.quantitative_screen_fail_open = False
        company.quantitative_candidates_by_code = {
            "600001": {
                "technical_factor": {
                    "weekly_trend_score": 70,
                    "relative_strength_score": 65,
                    "daily_entry_score": 60,
                },
                "quantitative_score": 67,
                "quantitative_screen": {"relative_strength_20d_pct": 3.1},
            }
        }
        signals = [
            {"symbol_code": "600001.SH", "symbol_name": "允许"},
            {"symbol_code": "000001.SZ", "symbol_name": "禁止"},
        ]

        filtered = company._restrict_to_quantitative_candidates(signals)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["symbol_code"], "600001.SH")
        self.assertEqual(filtered[0]["quantitative_score"], 67)
        self.assertEqual(filtered[0]["technical_factor"]["weekly_trend_score"], 70)


if __name__ == "__main__":
    unittest.main()

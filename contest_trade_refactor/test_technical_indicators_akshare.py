import unittest
from unittest.mock import patch

import pandas as pd
import requests

from data_source.technical_indicators_akshare import (
    TechnicalIndicatorsAkshare,
    compute_stock_technical_factor,
    compute_stock_technical_factor_from_history,
)
from utils.akshare_utils import CachedAksharePro


class TestTechnicalIndicatorsAkshare(unittest.TestCase):
    def test_failed_active_stock_cache_is_ignored(self):
        df = pd.DataFrame(
            [
                {
                    "content": (
                        "### 活跃个股技术面 (成交额前20)\n"
                        "获取失败: RemoteDisconnected"
                    )
                }
            ]
        )

        self.assertTrue(TechnicalIndicatorsAkshare._has_failed_active_stock_data(df))

    def test_active_stock_indicators_handles_string_change_pct(self):
        spot_df = pd.DataFrame(
            [
                {
                    "代码": "000001",
                    "名称": "平安银行",
                    "成交额": "100",
                    "涨跌幅": "+1.23",
                },
                {
                    "代码": "000002",
                    "名称": "万科A",
                    "成交额": "200",
                    "涨跌幅": "-0.50",
                },
            ]
        )
        dates = pd.date_range("2026-07-01", periods=25, freq="D")
        hist_df = pd.DataFrame(
            {
                "日期": dates.strftime("%Y-%m-%d"),
                "开盘": [10 + i * 0.1 for i in range(25)],
                "收盘": [10 + i * 0.1 for i in range(25)],
                "最高": [10.2 + i * 0.1 for i in range(25)],
                "最低": [9.8 + i * 0.1 for i in range(25)],
                "成交量": [1000000 + i * 1000 for i in range(25)],
            }
        )

        def fake_run(func_name, func_kwargs, verbose=False):
            if func_name == "stock_zh_a_spot_em":
                return spot_df
            if func_name == "stock_zh_a_hist":
                return hist_df
            raise AssertionError(f"unexpected func_name: {func_name}")

        source = TechnicalIndicatorsAkshare()
        with patch("data_source.technical_indicators_akshare.akshare_cached.run", side_effect=fake_run):
            report = source._compute_active_stock_indicators("20260807", "20260701", "20260807")

        self.assertIn("平安银行(000001)", report)
        self.assertLess(report.index("万科A(000002)"), report.index("平安银行(000001)"))
        self.assertIn("涨跌幅+1.23%", report)
        self.assertNotIn("获取失败", report)

    def test_stock_factor_computes_weekly_trend_and_relative_strength(self):
        dates = pd.date_range("2025-07-01", periods=260, freq="D")
        stock_close = [100 + i * 0.5 for i in range(260)]
        benchmark_close = [100 + i * 0.1 for i in range(260)]
        stock_df = pd.DataFrame(
            {
                "日期": dates.strftime("%Y-%m-%d"),
                "开盘": [value for value in stock_close],
                "收盘": stock_close,
                "最高": [value + 1 for value in stock_close],
                "最低": [value - 1 for value in stock_close],
                "成交量": [1000000 + i * 1000 for i in range(260)],
                "涨跌幅": [0.5] * 260,
            }
        )
        benchmark_df = pd.DataFrame(
            {
                "date": dates.strftime("%Y-%m-%d"),
                "close": benchmark_close,
            }
        )

        def fake_run(func_name, func_kwargs, verbose=False):
            if func_name == "stock_zh_a_hist":
                return stock_df
            if func_name == "stock_zh_index_daily":
                return benchmark_df
            raise AssertionError(f"unexpected func_name: {func_name}")

        with patch(
            "data_source.technical_indicators_akshare.akshare_cached.run",
            side_effect=fake_run,
        ):
            factor = compute_stock_technical_factor(
                symbol_code="600519.SH",
                symbol_name="贵州茅台",
                trade_date="20260811",
                start_date="20250701",
                end_date="20260811",
            )

        self.assertIsNotNone(factor)
        self.assertTrue(factor["weekly_data_available"])
        self.assertEqual(factor["weekly_trend"], "bullish")
        self.assertTrue(factor["relative_strength_available"])
        self.assertGreater(factor["relative_strength_20d_pct"], 0)
        self.assertGreater(factor["relative_strength_score"], 50)
        self.assertIn("daily_entry_score", factor)
        self.assertEqual(factor["weinstein_stage"], "stage_2_uptrend")
        self.assertTrue(factor["data_quality_valid"])

    def test_future_history_is_rejected_before_factor_calculation(self):
        dates = pd.date_range("2026-08-01", periods=25, freq="D")
        frame = pd.DataFrame(
            {
                "日期": dates.strftime("%Y-%m-%d"),
                "开盘": [10 + i * 0.1 for i in range(25)],
                "收盘": [10 + i * 0.1 for i in range(25)],
                "最高": [10.2 + i * 0.1 for i in range(25)],
                "最低": [9.8 + i * 0.1 for i in range(25)],
                "成交量": [1000] * 25,
            }
        )
        factor = compute_stock_technical_factor_from_history(
            frame,
            symbol_code="600519.SH",
            symbol_name="测试",
            trade_date="20260810",
        )
        self.assertIsNone(factor)

    def test_kline_retries_eastmoney_ten_times_before_tencent(self):
        client = CachedAksharePro(max_retries=10)
        calls = []
        fallback_df = pd.DataFrame({"ok": [1]})

        def fail_hist(**kwargs):
            calls.append(kwargs)
            raise requests.exceptions.ConnectionError("eastmoney unavailable")

        with (
            patch("utils.akshare_utils.ak.stock_zh_a_hist", side_effect=fail_hist),
            patch.object(client, "_stock_zh_a_hist_tx_fallback", return_value=fallback_df) as fallback,
            patch("utils.akshare_utils.time.sleep"),
        ):
            result = client._call_akshare(
                "stock_zh_a_hist",
                {"symbol": "300502", "period": "daily"},
                verbose=False,
            )

        self.assertIs(result, fallback_df)
        self.assertEqual(len(calls), 10)
        fallback.assert_called_once()


if __name__ == "__main__":
    unittest.main()

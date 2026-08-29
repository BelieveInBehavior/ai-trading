import unittest
from unittest.mock import patch

import pandas as pd
import requests

from data_source.technical_indicators_akshare import (
    _compute_atr,
    _compute_rsi,
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

        with (
            patch(
                "data_source.technical_indicators_akshare.get_stock_zh_a_hist",
                return_value=stock_df,
            ),
            patch(
                "data_source.technical_indicators_akshare.get_index_daily",
                return_value=benchmark_df,
            ),
        ):
            factor = compute_stock_technical_factor(
                symbol_code="600519.SH",
                symbol_name="贵州茅台",
                trade_date="20260811",
                start_date="20250701",
                end_date="20260811",
                ma_mode="ema",
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
        # MA 绝对值/新增多头结构字段
        self.assertIsNotNone(factor["ma5"])
        self.assertIsNotNone(factor["ma10"])
        self.assertIsNotNone(factor["ma20"])
        self.assertIn("ma5_gt_ma20", factor)
        self.assertIn("ma10_gt_ma20", factor)
        self.assertIn("ma5_gt_ma60", factor)
        self.assertIn("ma20_ge_ma60", factor)
        self.assertGreater(factor["ma5"], factor["ma10"])
        self.assertIn("close_above_ma10", factor)
        self.assertIn("close_above_ma20", factor)
        self.assertIn("ma10_slope_pct", factor)
        self.assertIn("ma20_slope_pct", factor)
        # 显式 EMA 路径被正确标记并输出周线/长期 EMA
        self.assertEqual(factor["ma_mode"], "ema")
        ema_ma10 = pd.Series(stock_close).ewm(span=10, adjust=False, min_periods=10).mean().iloc[-1]
        self.assertAlmostEqual(factor["ma10"], ema_ma10, places=4)
        self.assertGreater(factor["weekly_ma20"], 0)
        self.assertGreater(factor["weinstein_ma30"], 0)
        # 金融口径 OLS 残差/alpha/beta/r2 已输出
        self.assertIsNotNone(factor.get("beta_20d_vs_index"))
        self.assertIsNotNone(factor.get("beta_60d_vs_index"))
        self.assertIsNotNone(factor.get("alpha_20d_vs_index"))
        self.assertIsNotNone(factor.get("residual_rs_vs_index_20d"))
        self.assertIsNotNone(factor.get("residual_rs_vs_index_60d"))
        self.assertIsNotNone(factor.get("r2_20d_vs_index"))

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

    def test_kline_uses_tencent_fast_path_before_eastmoney_retry(self):
        # 当前实现先尝试腾讯直连（快路径），成功则不触发东财重试。
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
        self.assertEqual(len(calls), 0)
        fallback.assert_called_once()


class TechnicalIndicatorsMathTest(unittest.TestCase):
    def test_rsi_uses_wilder_smoothing(self):
        closes = pd.Series([100 + (i % 3) for i in range(30)], dtype=float)
        val = _compute_rsi(closes, 14)
        self.assertTrue(0.0 <= val <= 100.0)
        # flat/constant series should be 100% if no losses
        closes2 = pd.Series([100.0] * 30)
        self.assertEqual(_compute_rsi(closes2, 14), 100.0)

    def test_atr_uses_wilder_smoothing(self):
        closes = pd.Series(range(10, 40), dtype=float)
        highs = closes + 1.0
        lows = closes - 1.0
        val = _compute_atr(highs, lows, closes, 14)
        self.assertGreater(val, 0.0)


if __name__ == "__main__":
    unittest.main()

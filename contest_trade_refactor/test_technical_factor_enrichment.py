import unittest
from unittest.mock import patch

from main_loop import (
    _enrich_signals_with_technical_factors,
    _extract_technical_stock_factors,
)


class TestTechnicalFactorEnrichment(unittest.TestCase):
    def test_extracts_active_stock_technical_factor(self):
        data_factors = [
            {
                "agent_name": "technical_indicators_agent",
                "context_string": (
                    "## 技术指标分析报告 (20260807)\n\n"
                    "### 活跃个股技术面 (成交额前20)\n"
                    "新易盛(300502): 收盘420.95, 涨跌幅-0.22%, "
                    "MA20距离-10.5%, RSI=38.5, MACD=-7.204, 量比=1.02, 布林=中下"
                ),
            }
        ]

        factors = _extract_technical_stock_factors(data_factors)

        self.assertIn("300502", factors)
        self.assertEqual(factors["300502"]["symbol_name"], "新易盛")
        self.assertEqual(factors["300502"]["ma20_deviation_pct"], -10.5)

    def test_enriches_research_signal_with_technical_factor(self):
        data_factors = [
            {
                "agent_name": "technical_indicators_agent",
                "context_string": (
                    "## 技术指标分析报告 (20260807)\n\n"
                    "### 活跃个股技术面 (成交额前20)\n"
                    "新易盛(300502): 收盘420.95, 涨跌幅-0.22%, "
                    "MA20距离-10.5%, RSI=38.5, MACD=-7.204, 量比=1.02, 布林=中下"
                ),
            }
        ]
        signals = [
            {
                "symbol_code": "300502.SZ",
                "symbol_name": "新易盛",
                "action": "buy",
                "evidence_list": [],
            }
        ]

        enriched = _enrich_signals_with_technical_factors(signals, data_factors)

        self.assertEqual(enriched[0]["ma20_deviation_pct"], -10.5)
        self.assertEqual(enriched[0]["prev_day_gain_pct"], -0.22)
        self.assertIn("跌破20日线", enriched[0]["kline_description"])
        self.assertIn("technical_factor", enriched[0])

    def test_fetches_missing_candidate_technical_factor(self):
        signals = [
            {
                "symbol_code": "600489.SH",
                "symbol_name": "中金黄金",
                "action": "buy",
                "evidence_list": [],
            }
        ]
        fetched_factor = {
            "symbol_code": "600489",
            "symbol_name": "中金黄金",
            "report_date": "20260810",
            "close": 26.62,
            "change_pct": 1.99,
            "ma20_deviation_pct": 20.4,
            "rsi": 79.4,
            "macd": 1.155,
            "volume_ratio": 1.03,
            "bollinger": "上轨上方",
            "source_line": (
                "中金黄金(600489): 收盘26.62, 涨跌幅+1.99%, "
                "MA20距离+20.4%, RSI=79.4, MACD=1.155, 量比=1.03, 布林=上轨上方"
            ),
        }

        with patch("main_loop.compute_stock_technical_factor", return_value=fetched_factor) as compute:
            enriched = _enrich_signals_with_technical_factors(
                signals,
                data_factors=[],
                trigger_time="2026-08-10 19:13:31",
            )

        compute.assert_called_once()
        self.assertEqual(enriched[0]["ma20_deviation_pct"], 20.4)
        self.assertEqual(enriched[0]["prev_day_gain_pct"], 1.99)
        self.assertIn("站上20日线", enriched[0]["kline_description"])

    def test_ignores_stale_technical_factor_when_trigger_date_is_newer(self):
        data_factors = [
            {
                "agent_name": "technical_indicators_agent",
                "context_string": (
                    "## 技术指标分析报告 (20260807)\n\n"
                    "### 活跃个股技术面 (成交额前20)\n"
                    "新易盛(300502): 收盘420.95, 涨跌幅-0.22%, "
                    "MA20距离-10.5%, RSI=38.5, MACD=-7.204, 量比=1.02, 布林=中下"
                ),
            }
        ]
        signals = [
            {
                "symbol_code": "300502.SZ",
                "symbol_name": "新易盛",
                "action": "buy",
                "evidence_list": [],
            }
        ]
        fresh_factor = {
            "symbol_code": "300502",
            "symbol_name": "新易盛",
            "report_date": "20260810",
            "close": 399.6,
            "change_pct": -5.07,
            "ma20_deviation_pct": -14.0,
            "rsi": 29.3,
            "macd": -7.021,
            "volume_ratio": 1.08,
            "bollinger": "中下",
            "source_line": (
                "新易盛(300502): 收盘399.60, 涨跌幅-5.07%, "
                "MA20距离-14.0%, RSI=29.3, MACD=-7.021, 量比=1.08, 布林=中下"
            ),
        }

        with patch("main_loop.compute_stock_technical_factor", return_value=fresh_factor):
            enriched = _enrich_signals_with_technical_factors(
                signals,
                data_factors=data_factors,
                trigger_time="2026-08-10 19:13:31",
            )

        self.assertEqual(enriched[0]["technical_factor"]["report_date"], "20260810")
        self.assertEqual(enriched[0]["ma20_deviation_pct"], -14.0)

    def test_marks_missing_kline_when_candidate_fetch_fails(self):
        signals = [
            {
                "symbol_code": "000620.SZ",
                "symbol_name": "立新能源",
                "action": "buy",
                "evidence_list": [],
            }
        ]

        with patch("main_loop.compute_stock_technical_factor", return_value=None):
            enriched = _enrich_signals_with_technical_factors(
                signals,
                data_factors=[],
                trigger_time="2026-08-10 19:13:31",
            )

        self.assertNotIn("technical_factor", enriched[0])
        self.assertIn("missing_kline", enriched[0]["data_quality_warnings"])


if __name__ == "__main__":
    unittest.main()

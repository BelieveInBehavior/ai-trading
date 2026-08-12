import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from tools import stock_summary_akshare


class _FakeSearchWeb:
    async def ainvoke(self, _payload):
        return ["新闻摘要"]


class TestStockSummaryAkshare(unittest.IsolatedAsyncioTestCase):
    async def test_returns_kline_fallback_when_llm_times_out(self):
        all_data = {
            "kline_description": "最新交易日: 2026-08-10\n5/10/20日均线: 2.80 / 2.82 / 2.79",
            "technical_analysis": "技术指标摘要: MA5/10/20=2.80/2.82/2.79; RSI14=46.10",
            "financial_summary": "",
            "sector_analysis": "",
            "stock_moneyflow_analysis": "",
            "intraday_chart_base64": None,
            "kline_chart_base64": None,
        }

        with (
            patch.object(stock_summary_akshare, "get_all_stock_data", return_value=all_data),
            patch.object(stock_summary_akshare, "search_web", new=_FakeSearchWeb()),
            patch.object(
                stock_summary_akshare,
                "call_llm_for_comprehensive_analysis",
                new=AsyncMock(side_effect=asyncio.TimeoutError()),
            ),
        ):
            result = await stock_summary_akshare.analyze_stock_basic_info(
                "CN-Stock",
                "000620.SZ",
                "立新能源",
                "2026-08-10 21:43:29",
            )

        self.assertIn("技术面摘要（规则兜底）", result)
        self.assertIn("最新交易日: 2026-08-10", result)
        self.assertIn("5/10/20日均线", result)
        self.assertIn("LLM综合分析未在限定时间内完成", result)


if __name__ == "__main__":
    unittest.main()

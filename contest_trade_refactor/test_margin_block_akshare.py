import asyncio
import unittest

from data_source.block_trade_akshare import BlockTradeAkshare
from data_source.margin_trading_akshare import MarginTradingAkshare


class TestMarginBlockAkshare(unittest.TestCase):
    def test_margin_report_not_failed(self):
        ds = MarginTradingAkshare()
        df = asyncio.run(ds.get_data("2026-08-11 11:23:16"))
        self.assertFalse(df.empty)
        content = df.iloc[0]["content"]
        self.assertNotIn("融资融券数据获取失败", content)
        self.assertIn("融资融券异动分析", content)

    def test_block_trade_report_not_failed(self):
        ds = BlockTradeAkshare()
        df = asyncio.run(ds.get_data("2026-08-11 11:23:16"))
        self.assertFalse(df.empty)
        content = df.iloc[0]["content"]
        self.assertNotIn("大宗交易数据获取失败", content)
        self.assertIn("大宗交易折溢价分析", content)


if __name__ == "__main__":
    unittest.main()

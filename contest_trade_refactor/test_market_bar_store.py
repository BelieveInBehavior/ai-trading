import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from utils.market_bar_store import MarketBarStore, reset_market_bar_store
from utils.cn_price_provider import AKSHARE_COLUMNS, get_stock_zh_a_hist


def _bars(dates, close0=10.0):
    rows = []
    for i, day in enumerate(dates):
        close = close0 + i
        rows.append(
            {
                "日期": day,
                "股票代码": "600519",
                "开盘": close,
                "收盘": close,
                "最高": close + 1,
                "最低": close - 1,
                "成交量": 1000 + i,
                "成交额": 10000 + i,
                "振幅": 1.0,
                "涨跌幅": 1.0,
                "涨跌额": 1.0,
                "换手率": 1.0,
            }
        )
    return pd.DataFrame(rows)


class TestMarketBarStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = reset_market_bar_store(Path(self.tmp.name))

    def tearDown(self):
        reset_market_bar_store()
        self.tmp.cleanup()

    def test_upsert_then_asof_slice_hides_future_bars(self):
        self.store.upsert_stock(
            "600519",
            _bars(["2026-06-01", "2026-06-02", "2026-06-03"]),
        )
        local = self.store.load_stock("600519")
        sliced = self.store.slice(local, "20260601", "20260602", date_col="日期")
        self.assertEqual(list(sliced["日期"]), ["2026-06-01", "2026-06-02"])

    def test_covers_and_missing_tail_only(self):
        local = _bars(["2026-06-01", "2026-06-02"])
        self.assertTrue(self.store.covers(local, "20260601", "20260602", date_col="日期"))
        self.assertFalse(self.store.covers(local, "20260601", "20260603", date_col="日期"))
        self.assertEqual(
            self.store.missing_ranges(local, "20260601", "20260603", date_col="日期"),
            [("20260603", "20260603")],
        )

    def test_hist_uses_store_without_refetch(self):
        self.store.upsert_stock("600519", _bars(["2026-06-01", "2026-06-02", "2026-06-03"]))
        with patch("utils.cn_price_provider._fetch_remote_stock_hist") as fetch:
            out = get_stock_zh_a_hist("600519.SH", "20260601", "20260602", adjust="qfq")
        fetch.assert_not_called()
        self.assertEqual(list(out["日期"]), ["2026-06-01", "2026-06-02"])
        self.assertIn("收盘", out.columns)

    def test_hist_fetches_only_missing_tail_and_appends(self):
        self.store.upsert_stock("600519", _bars(["2026-06-01", "2026-06-02"]))
        tail = _bars(["2026-06-03"], close0=12.0)

        def fake_fetch(symbol, start_date, end_date, adjust="qfq", verbose=False):
            self.assertEqual(start_date, "20260603")
            self.assertEqual(end_date, "20260603")
            return tail

        with patch("utils.cn_price_provider._fetch_remote_stock_hist", side_effect=fake_fetch) as fetch:
            out = get_stock_zh_a_hist("600519", "20260601", "20260603", adjust="qfq")
        fetch.assert_called_once()
        self.assertEqual(list(out["日期"]), ["2026-06-01", "2026-06-02", "2026-06-03"])
        stored = self.store.load_stock("600519")
        self.assertEqual(list(stored["日期"]), ["2026-06-01", "2026-06-02", "2026-06-03"])

    def test_asof_env_clips_even_when_store_has_later_bars(self):
        self.store.upsert_stock("600519", _bars(["2026-06-01", "2026-06-02", "2026-08-25"]))
        with (
            patch.dict("os.environ", {"CONTEST_TRADE_ASOF_DATE": "20260602"}),
            patch("utils.cn_price_provider._fetch_remote_stock_hist") as fetch,
        ):
            out = get_stock_zh_a_hist("600519", "20260601", "20260825", adjust="qfq")
        fetch.assert_not_called()
        self.assertEqual(list(out["日期"]), ["2026-06-01", "2026-06-02"])
        self.assertNotIn("2026-08-25", set(out["日期"]))

    def test_empty_columns_match_provider_schema(self):
        with patch("utils.cn_price_provider._fetch_remote_stock_hist", return_value=pd.DataFrame(columns=AKSHARE_COLUMNS)):
            out = get_stock_zh_a_hist("000001", "20260601", "20260602")
        self.assertTrue(out.empty)


if __name__ == "__main__":
    unittest.main()

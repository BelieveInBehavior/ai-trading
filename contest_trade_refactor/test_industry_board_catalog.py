import json
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from utils.industry_board_catalog import load_catalog, resolve_industry_board
from utils.industry_board_constants import INDUSTRY_BOARD_RESOLVE, TENCENT_INDUSTRY_CODES, THS_INDUSTRY_CODES
from utils.sector_flow_provider import (
    _normalize_board_history,
    get_industry_daily_history,
)


CATALOG = {
    "tencent": {
        "通信设备": "pt01801102",
        "通信服务": "pt01801223",
        "股份制银行Ⅱ": "pt01801783",
        "国有大型银行Ⅱ": "pt01801782",
        "能源金属": "pt01801056",
        "半导体": "pt018010xx",
        "食品加工": "pt01801124",
    },
    "ths": {
        "通信设备": "881102",
        "通信服务": "881223",
        "银行": "881155",
        "能源金属": "881056",
        "半导体": "881121",
        "食品加工制造": "881124",
    },
}


class TestIndustryBoardCatalog(unittest.TestCase):
    def test_resolve_eastmoney_l3_to_tencent_and_ths(self):
        cases = {
            "通信": ("通信设备", "pt01801102", "通信设备"),
            "银行Ⅱ": ("股份制银行Ⅱ", "pt01801783", "银行"),
            "数字芯片设计": ("半导体", "pt018010xx", "半导体"),
            "锂": ("能源金属", "pt01801056", "能源金属"),
            "食品饮料": ("食品加工", "pt01801124", "食品加工制造"),
        }
        for query, (tx_name, tx_code, ths_name) in cases.items():
            resolved = resolve_industry_board(query, catalog=CATALOG)
            self.assertEqual(resolved.tencent_name, tx_name, query)
            self.assertEqual(resolved.tencent_code, tx_code, query)
            self.assertEqual(resolved.ths_name, ths_name, query)

    def test_unknown_name_does_not_invent_ths_symbol(self):
        resolved = resolve_industry_board("不存在的板块XYZ", catalog=CATALOG)
        self.assertIsNone(resolved.tencent_code)
        self.assertIsNone(resolved.ths_name)

    def test_ths_history_without_pct_chg_is_still_normalized(self):
        raw = pd.DataFrame(
            [
                {"日期": "2026-08-24", "开盘价": 100.0, "收盘价": 110.0, "最高价": 111.0, "最低价": 99.0},
                {"日期": "2026-08-25", "开盘价": 110.0, "收盘价": 121.0, "最高价": 122.0, "最低价": 109.0},
            ]
        )
        out = _normalize_board_history(raw, "通信")
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(float(out.iloc[1]["pct_chg"]), 10.0)

    def test_history_uses_tencent_code_not_eastmoney_name(self):
        tx = pd.DataFrame(
            [
                {"date": "2026-08-24", "open": 1, "close": 10, "high": 11, "low": 9, "amount": 1},
                {"date": "2026-08-25", "open": 10, "close": 12, "high": 13, "low": 9, "amount": 1},
            ]
        )
        with (
            patch("utils.sector_flow_provider.akshare_cached.run", side_effect=Exception("eastmoney down")),
            patch("utils.sector_flow_provider._resolve_industry_board", return_value=resolve_industry_board("通信", catalog=CATALOG)),
            patch("utils.sector_flow_provider.ak.stock_zh_index_daily_tx", return_value=tx) as tx_mock,
            patch("utils.sector_flow_provider.ak.stock_board_industry_index_ths") as ths_mock,
        ):
            df = get_industry_daily_history("通信", "20260801", "20260825")

        tx_mock.assert_called_once()
        self.assertEqual(tx_mock.call_args.kwargs["symbol"], "pt01801102")
        ths_mock.assert_not_called()
        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[0]["board_name"], "通信")

    def test_history_maps_ths_name_and_skips_unmapped(self):
        ths = pd.DataFrame(
            [
                {"日期": "2026-08-24", "开盘价": 1, "收盘价": 10, "最高价": 11, "最低价": 9},
                {"日期": "2026-08-25", "开盘价": 10, "收盘价": 11, "最高价": 12, "最低价": 9},
            ]
        )
        resolved = resolve_industry_board("通信", catalog=CATALOG)
        with (
            patch("utils.sector_flow_provider.akshare_cached.run", side_effect=Exception("eastmoney down")),
            patch("utils.sector_flow_provider._resolve_industry_board", return_value=resolved),
            patch("utils.sector_flow_provider.ak.stock_zh_index_daily_tx", return_value=pd.DataFrame()),
            patch("utils.sector_flow_provider.ak.stock_board_industry_index_ths", return_value=ths) as ths_mock,
        ):
            df = get_industry_daily_history("通信", "20260801", "20260825")

        ths_mock.assert_called_once()
        self.assertEqual(ths_mock.call_args.kwargs["symbol"], "通信设备")
        self.assertEqual(len(df), 2)

        unmapped = resolve_industry_board("不存在的板块XYZ", catalog=CATALOG)
        with (
            patch("utils.sector_flow_provider.akshare_cached.run", side_effect=Exception("eastmoney down")),
            patch("utils.sector_flow_provider._resolve_industry_board", return_value=unmapped),
            patch("utils.sector_flow_provider.ak.stock_zh_index_daily_tx") as tx_mock,
            patch("utils.sector_flow_provider.ak.stock_board_industry_index_ths") as ths_mock,
        ):
            empty = get_industry_daily_history("不存在的板块XYZ", "20260801", "20260825")

        tx_mock.assert_not_called()
        ths_mock.assert_not_called()
        self.assertTrue(empty.empty)

    def test_builtin_constants_cover_industry_map_without_network(self):
        self.assertGreaterEqual(len(TENCENT_INDUSTRY_CODES), 100)
        self.assertGreaterEqual(len(THS_INDUSTRY_CODES), 80)
        industry_map = json.loads(
            Path("utils/cache/market_manager/industry_map.json").read_text(encoding="utf-8")
        )
        names = sorted({str(v).strip() for v in industry_map.values() if v})
        missing = [name for name in names if name not in INDUSTRY_BOARD_RESOLVE]
        self.assertEqual(missing, [])

        with (
            patch("utils.industry_board_catalog.load_catalog") as load_mock,
            patch("requests.get") as req_mock,
        ):
            resolved = resolve_industry_board("通信")
        load_mock.assert_not_called()
        req_mock.assert_not_called()
        self.assertEqual(resolved.tencent_name, "通信设备")
        self.assertEqual(resolved.tencent_code, "pt01801102")
        self.assertEqual(resolved.ths_name, "通信设备")
        self.assertEqual(resolved.ths_code, "881129")

        catalog = load_catalog(refresh=True)
        missing_live = []
        for name in names:
            hit = resolve_industry_board(name)
            if not hit.has_tencent and not hit.has_ths:
                missing_live.append(name)
        self.assertEqual(missing_live, [])
        self.assertEqual(catalog["tencent"]["通信设备"], "pt01801102")


if __name__ == "__main__":
    unittest.main()

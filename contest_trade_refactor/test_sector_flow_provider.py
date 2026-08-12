import unittest
from unittest.mock import patch

import pandas as pd

from data_source.hot_money_akshare import HotMoneyAkshare
from utils.sector_flow_provider import (
    _normalize_sector_frame,
    get_concept_board_data,
    get_industry_board_data,
)


class TestSectorFlowProvider(unittest.TestCase):
    def test_concept_flow_fallback_normalizes_akshare_fund_flow(self):
        primary_without_flow = pd.DataFrame(
            [
                {"板块名称": "测试概念", "涨跌幅": 1.0},
            ]
        )
        fallback = pd.DataFrame(
            [
                {
                    "行业": "养鸡",
                    "行业-涨跌幅": 4.3,
                    "流入资金": 17.24,
                    "流出资金": 12.52,
                    "净额": 4.72,
                    "公司家数": 22,
                    "领涨股": "益生股份",
                    "领涨股-涨跌幅": 10.02,
                }
            ]
        )

        with (
            patch("utils.sector_flow_provider.akshare_cached.run", return_value=primary_without_flow),
            patch("utils.sector_flow_provider.ak.stock_fund_flow_concept", return_value=fallback),
        ):
            df = get_concept_board_data(require_flow=True, allow_industry_fallback=False)

        self.assertEqual(df.iloc[0]["板块名称"], "养鸡")
        self.assertEqual(df.iloc[0]["数据源"], "akshare:stock_fund_flow_concept")
        self.assertAlmostEqual(df.iloc[0]["主力净流入"], 4.72e8)
        self.assertEqual(df.iloc[0]["成分股数量"], 22)

    def test_industry_flow_fallback_normalizes_akshare_fund_flow(self):
        fallback = pd.DataFrame(
            [
                {
                    "行业": "医疗服务",
                    "行业-涨跌幅": 4.59,
                    "流入资金": 253.27,
                    "流出资金": 246.82,
                    "净额": 6.46,
                    "公司家数": 56,
                }
            ]
        )

        with (
            patch("utils.sector_flow_provider.akshare_cached.run", side_effect=Exception("eastmoney down")),
            patch("utils.sector_flow_provider.ak.stock_fund_flow_industry", return_value=fallback),
        ):
            df = get_industry_board_data(require_flow=True)

        self.assertEqual(df.iloc[0]["板块名称"], "医疗服务")
        self.assertEqual(df.iloc[0]["数据源"], "akshare:stock_fund_flow_industry")
        self.assertAlmostEqual(df.iloc[0]["主力净流入"], 6.46e8)

    def test_tushare_moneyflow_shape_is_normalized(self):
        raw = pd.DataFrame(
            [
                {
                    "trade_date": "20260810",
                    "ts_code": "BK1234",
                    "name": "电力设备",
                    "pct_change": "2.5",
                    "net_amount": 123000000,
                    "rank": 1,
                }
            ]
        )

        df = _normalize_sector_frame(
            raw,
            source_name="tushare:moneyflow_ind_dc",
            board_type="概念/行业",
            money_unit="yuan",
        )

        self.assertEqual(df.iloc[0]["板块名称"], "电力设备")
        self.assertEqual(df.iloc[0]["板块代码"], "BK1234")
        self.assertEqual(df.iloc[0]["主力净流入"], 123000000)
        self.assertEqual(df.iloc[0]["涨跌幅"], 2.5)

    def test_hot_money_report_includes_flow_when_counts_missing(self):
        concept_df = pd.DataFrame(
            [
                {
                    "板块名称": "猪肉",
                    "涨跌幅": 4.07,
                    "主力净流入": 13.32e8,
                    "数据源": "akshare:stock_fund_flow_concept",
                }
            ]
        )

        report = HotMoneyAkshare()._construct_analysis_text(
            "20260810",
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            concept_df,
            pd.DataFrame(),
        )

        self.assertIn("猪肉", report)
        self.assertIn("主力净流入+13.32亿", report)
        self.assertIn("akshare:stock_fund_flow_concept", report)


if __name__ == "__main__":
    unittest.main()

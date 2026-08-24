import unittest
import tempfile
import json
import os

import pandas as pd

from utils.sector_enrichment import (
    _compute_sector_residual,
    enrich_factor_with_sector,
    build_sector_snapshot_from_factor_store,
    build_code_sector_snapshot,
    enrich_factor_with_sector_by_name,
    resolve_sector_board_name,
    compute_ex_self_sector_metrics,
    enrich_factor_with_ex_self,
)


class TestSectorEnrichment(unittest.TestCase):
    def have_sector_fields(self, factor, sector_map):
        out = enrich_factor_with_sector(factor, sector_map)
        self.assertEqual(out["sector_1d_return"], 2.5)
        self.assertEqual(out["sector_rank"], 3)
        self.assertEqual(out["stock_vs_sector_strength"], 1.2)

    def test_enrich_factor_adds_sector_fields(self):
        factor = {"symbol_code": "600519.SH", "symbol_name": "贵州茅台"}
        sector_map = {
            "600519.SH": {
                "sector_1d_return": 2.5,
                "sector_rank": 3,
                "stock_vs_sector_strength": 1.2,
            }
        }
        out = enrich_factor_with_sector(factor, sector_map)
        self.assertEqual(out["sector_1d_return"], 2.5)
        self.assertEqual(out["sector_rank"], 3)
        self.assertEqual(out["stock_vs_sector_strength"], 1.2)


    def test_enrich_calculates_stock_vs_sector_never_none(self):
        factor = {
            "symbol_code": "600519.SH",
            "symbol_name": "贵州茅台",
            "change_pct": 5.0,
            "ret_3d_pct": 9.0,
            "ret_5d_pct": 12.0,
            "ret_10d_pct": 20.0,
        }
        sector_map = {
            "600519.SH": {
                "sector_1d_return": 2.0,
                "sector_3d_return": 5.0,
                "sector_5d_return": 8.0,
                "sector_10d_return": 15.0,
                "sector_rank": 3,
                "stock_vs_sector_strength": None,
            }
        }
        out = enrich_factor_with_sector(factor, sector_map)
        self.assertEqual(out["stock_vs_sector_1d"], 3.0)
        self.assertEqual(out["stock_vs_sector_3d"], 4.0)
        self.assertEqual(out["stock_vs_sector_5d"], 4.0)
        self.assertEqual(out["stock_vs_sector_10d"], 5.0)
        self.assertEqual(out["stock_vs_sector_strength"], 4.0)

    def test_enrich_no_sector_keeps_neutral(self):
        factor = {"symbol_code": "000001.SZ", "symbol_name": "平安银行"}
        out = enrich_factor_with_sector(factor, {})
        self.assertNotIn("sector_1d_return", out)

    def test_build_snapshot_from_csv_and_enrich_by_name(self):
        with tempfile.TemporaryDirectory() as td:
            csv_path = os.path.join(td, "20260813.csv")
            pd.DataFrame(
                [
                    {
                        "symbol_code": "医疗服务",
                        "symbol_name": "医疗服务",
                        "factor_date": "20260813",
                        "factor_value": 1.0,
                        "metadata_json": json.dumps({"change_pct": 3.99}),
                    },
                    {
                        "symbol_code": "白酒",
                        "symbol_name": "白酒",
                        "factor_date": "20260813",
                        "factor_value": -1.0,
                        "metadata_json": json.dumps({"change_pct": 0.06}),
                    },
                ]
            ).to_csv(csv_path, index=False)

            snap = build_sector_snapshot_from_factor_store(td, trade_date="20260813")
            self.assertEqual(snap["医疗服务"]["sector_1d_return"], 3.99)
            self.assertEqual(snap["医疗服务"]["sector_rank"], 1)
            self.assertEqual(snap["白酒"]["sector_rank"], 2)
            factor = {"symbol_name": "药明康德", "symbol_code": "600276.SH"}
            out = enrich_factor_with_sector_by_name(factor, snap, "医疗服务")
            self.assertEqual(out["sector_1d_return"], 3.99)

    def test_build_code_function(self):
        by_name = {"医疗服务": {"sector_1d_return": 3.99, "sector_rank": 1}}
        industry_map = {"600276.SH": "医疗服务", "000001.SZ": "银行"}
        out = build_code_sector_snapshot(industry_map, by_name)
        self.assertIn("600276.SH", out)
        self.assertNotIn("000001.SZ", out)
        self.assertEqual(out["600276.SH"]["sector_1d_return"], 3.99)

    def test_resolve_eligible_main_trend_boards(self):
        """20260821 eligible 池应能解析到东财二级板块，而非默认放行。"""
        by_name = {
            "生物制品": {"sector_1d_return": -2.73, "sector_rank": 84},
            "贵金属": {"sector_1d_return": 1.0, "sector_rank": 10},
            "港口航运": {"sector_1d_return": 0.28, "sector_rank": 20},
            "煤炭开采加工": {"sector_1d_return": -1.0, "sector_rank": 30},
            "化学制药": {"sector_1d_return": -3.0, "sector_rank": 40},
            "医疗器械": {"sector_1d_return": -2.0, "sector_rank": 50},
            "银行": {"sector_1d_return": -0.6, "sector_rank": 50},
        }
        cases = [
            ("其他生物制品", "近岸蛋白", "生物制品"),
            ("有色金属", "西部黄金", "贵金属"),
            ("交通运输", "中远海控", "港口航运"),
            ("焦煤", "淮北矿业", "煤炭开采加工"),
            ("医药生物", "康希诺", "化学制药"),
            ("体外诊断", "赛科希德", "医疗器械"),
            ("农商行Ⅲ", "沪农商行", "银行"),
        ]
        for industry, symbol_name, expected in cases:
            self.assertEqual(
                resolve_sector_board_name(industry, by_name, symbol_name=symbol_name),
                expected,
                msg=f"{industry}/{symbol_name}",
            )
        by_name = {
            "生物制品": {
                "sector_1d_return": -2.73,
                "sector_rank": 84,
            }
        }
        self.assertEqual(resolve_sector_board_name("其他生物制品", by_name), "生物制品")
        industry_map = {"688137.SH": "其他生物制品"}
        out = build_code_sector_snapshot(industry_map, by_name)
        self.assertIn("688137.SH", out)
        self.assertEqual(out["688137.SH"]["sector_name"], "生物制品")
        self.assertEqual(out["688137.SH"]["industry_name"], "其他生物制品")
        self.assertEqual(out["688137.SH"]["sector_1d_return"], -2.73)


if __name__ == "__main__":
    unittest.main()


class SectorResidualScaleTest(unittest.TestCase):
    def test_sector_ols_uses_percent_to_decimal_and_returns_percent_based_residual(self):
        # pct_chg 以“百分数”存储。让板块收益率恒定 1%，个股 = 2*板块 + 0.1%（都在 percent 口径）。
        # 金融回归应先转成小数，beta 应 ≈2.0，alpha（年周）应 ≈0.1%，残差应 ≈0。
        dates = pd.date_range("2026-01-01", periods=30, freq="B")
        sector = [{"date": str(d.date()), "pct_chg": 1.0} for d in dates]
        stock = [{"date": str(d.date()), "pct_chg": 2.0 + 0.1} for d in dates]
        out = _compute_sector_residual(stock, sector, window=20)
        self.assertAlmostEqual(out["beta"], 2.0, places=4)
        self.assertGreater(out["residual"], -0.0001)
        self.assertLess(out["residual"], 0.0001)
        self.assertAlmostEqual(out["alpha"], 0.1, places=4)


class SectorExSelfMetricsTest(unittest.TestCase):
    def test_ex_self_returns_and_breadth(self):
        snap = {
            "600519.SH": {
                "sector_1d_return": 3.0,
                "sector_5d_return": 5.0,
                "stock_vs_sector_strength": None,
                "上涨家数": 8,
                "下跌家数": 2,
                "sector_daily_returns": [],
            }
        }
        stock_daily = [
            {"date": "2026-08-12", "pct_chg": 1.0},
            {"date": "2026-08-13", "pct_chg": 2.0},
            {"date": "2026-08-14", "pct_chg": -0.5},
            {"date": "2026-08-15", "pct_chg": 1.5},
            {"date": "2026-08-18", "pct_chg": 3.0},
        ]
        out = compute_ex_self_sector_metrics(snap, "600519.SH", "白酒", stock_daily_returns=stock_daily)
        self.assertEqual(out["sector_return_ex_self_1d"], 0.0)  # 3.0 - 3.0
        self.assertAlmostEqual(out["sector_return_ex_self_5d"], 5.0 - 7.1637, places=3)  # stock 5d compound
        self.assertAlmostEqual(out["sector_breadth_ex_self"], (8 - 1) / 9.0, places=4)
        self.assertEqual(out.get("sector_breadth_total"), 8 / 10.0)

    def test_factor_enrich_adds_ex_self_fields(self):
        factor = {
            "symbol_code": "600519.SH",
            "symbol_name": "贵州茅台",
            "sector_name": "白酒",
            "change_pct": 2.0,
            "ret_5d_pct": 6.0,
            "stock_daily_returns": [{"date": "2026-08-18", "pct_chg": 2.0}],
        }
        snap = {
            "600519.SH": {"sector_1d_return": 1.0, "sector_5d_return": 3.0,
                           "上涨家数": 5, "下跌家数": 2}
        }
        out = enrich_factor_with_ex_self(factor, snap)
        self.assertEqual(out["sector_return_ex_self_1d"], -1.0)
        self.assertEqual(out["sector_breadth_ex_self"], round((5 - 1) / (7 - 1), 4) if (7 - 1) > 0 else 0)


if __name__ == "__main__":
    unittest.main()

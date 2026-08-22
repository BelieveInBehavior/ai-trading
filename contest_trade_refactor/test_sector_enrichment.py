import unittest
import tempfile
import json
import os

import pandas as pd

from utils.sector_enrichment import (
    enrich_factor_with_sector,
    build_sector_snapshot_from_factor_store,
    build_code_sector_snapshot,
    enrich_factor_with_sector_by_name,
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


if __name__ == "__main__":
    unittest.main()

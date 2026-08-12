import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tools.factor_backtest import FactorBacktester, FactorRecord


class TestFactorBacktest(unittest.TestCase):
    def test_next_open_return_includes_costs(self):
        prices = pd.DataFrame(
            {
                "日期": pd.to_datetime(["2026-08-01", "2026-08-03", "2026-08-04"]),
                "开盘": [10.0, 11.0, 12.0],
                "最高": [10.5, 11.5, 12.5],
                "最低": [9.5, 10.5, 11.5],
                "收盘": [10.0, 11.0, 12.0],
            }
        )
        record = FactorRecord("600001", "测试", "20260801", "factor", 1.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            backtester = FactorBacktester(
                horizons=[1],
                output_dir=Path(tmpdir),
                commission_bps=0,
                stamp_duty_bps=0,
                slippage_bps=0,
            )
            with patch.object(backtester, "_get_price", return_value=prices.rename(
                columns={
                    "日期": "date",
                    "开盘": "open",
                    "最高": "high",
                    "最低": "low",
                    "收盘": "close",
                }
            )):
                row = backtester._evaluate_single(record, "20260801", "20260805", pd.DataFrame())
            self.assertIsNotNone(row)
            self.assertAlmostEqual(row["entry_price"], 11.0)
            self.assertAlmostEqual(row["ret_t1"], 12.0 / 11.0 - 1.0)

    def test_run_persists_walk_forward_validation(self):
        dates = pd.date_range("2025-01-01", periods=500, freq="D")
        prices = pd.DataFrame(
            {
                "date": dates,
                "open": [10.0 + i * 0.01 for i in range(500)],
                "high": [10.5 + i * 0.01 for i in range(500)],
                "low": [9.5 + i * 0.01 for i in range(500)],
                "close": [10.0 + i * 0.01 for i in range(500)],
            }
        )
        records = [
            FactorRecord(
                symbol_code="600001",
                symbol_name="测试",
                factor_date=date.strftime("%Y%m%d"),
                factor_name="factor",
                factor_value=float(index),
            )
            for index, date in enumerate(dates)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            backtester = FactorBacktester(
                horizons=[1],
                output_dir=Path(tmpdir),
                commission_bps=0,
                stamp_duty_bps=0,
                slippage_bps=0,
            )
            with patch.object(backtester, "_get_price", return_value=prices):
                result = backtester.run(records, "factor")

            self.assertEqual(result.walk_forward["status"], "ok")
            self.assertGreaterEqual(result.walk_forward["test_samples"], 30)
            summary_files = list((Path(tmpdir) / "factor").glob("summary_*.json"))
            self.assertEqual(len(summary_files), 1)
            with summary_files[0].open("r", encoding="utf-8") as handle:
                summary = json.load(handle)
            self.assertEqual(summary["walk_forward"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()

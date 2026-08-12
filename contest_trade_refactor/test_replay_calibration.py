import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tools.news_signal_backtest import CsvPriceProvider
from tools.replay_calibration import calibrate
from utils.threshold_manager import ThresholdManager


class TestReplayCalibration(unittest.TestCase):
    def test_threshold_calibration_requires_out_of_sample_result(self):
        manager = ThresholdManager()
        result = manager.auto_calibrate(
            "individual_fund_flow",
            {
                "ic_values": {"t1": 0.10},
                "horizons": {"t1": {"hit_rate": 0.60}},
            },
        )
        self.assertEqual(result["status"], "blocked_no_out_of_sample")

    def test_calibration_updates_and_filters_watch_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            signal_dir = root / "signals"
            price_dir = root / "prices"
            report_dir = root / "reports"
            calib_path = root / "probability_calibration.json"
            signal_dir.mkdir(parents=True, exist_ok=True)
            price_dir.mkdir(parents=True, exist_ok=True)

            payload_buy_1 = {
                "trigger_time": "2026-08-01 09:30:00",
                "best_signals": [
                    {
                        "symbol_code": "600001.SH",
                        "buy_score": 80,
                        "probability_value": 0.80,
                        "action": "买入",
                        "buy_decision": "buy",
                    }
                ],
            }
            payload_buy_2 = {
                "trigger_time": "2026-08-02 09:30:00",
                "best_signals": [
                    {
                        "symbol_code": "000001.SZ",
                        "buy_score": 78,
                        "probability_value": 0.70,
                        "action": "买入",
                        "buy_decision": "buy",
                    }
                ],
            }
            payload_watch = {
                "trigger_time": "2026-08-03 09:30:00",
                "best_signals": [
                    {
                        "symbol_code": "300001.SZ",
                        "buy_score": 85,
                        "probability_value": 0.90,
                        "action": "买入",
                        "buy_decision": "watch",
                    }
                ],
            }

            for idx, payload in enumerate([payload_buy_1, payload_buy_2, payload_watch], start=1):
                with open(signal_dir / f"decision_{idx}.json", "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)

            pd.DataFrame(
                {
                    "date": [
                        "2026-08-01",
                        "2026-08-02",
                        "2026-08-03",
                        "2026-08-04",
                        "2026-08-05",
                    ],
                    "close": [10, 11, 12, 12, 13],
                }
            ).to_csv(price_dir / "600001.csv", index=False)

            pd.DataFrame(
                {
                    "date": [
                        "2026-08-01",
                        "2026-08-02",
                        "2026-08-03",
                        "2026-08-04",
                        "2026-08-05",
                    ],
                    "close": [10, 9, 8, 8, 8],
                }
            ).to_csv(price_dir / "000001.csv", index=False)

            pd.DataFrame(
                {
                    "date": [
                        "2026-08-01",
                        "2026-08-02",
                        "2026-08-03",
                        "2026-08-04",
                        "2026-08-05",
                    ],
                    "close": [10, 10.2, 10.1, 10.3, 10.4],
                }
            ).to_csv(price_dir / "300001.csv", index=False)

            provider = CsvPriceProvider(price_dir)
            signal_files = sorted(signal_dir.glob("*.json"))

            result = calibrate(
                signal_files=signal_files,
                provider=provider,
                benchmark_symbol="",
                min_samples=2,
                output_calibration_path=calib_path,
                report_dir=report_dir,
                buys_only=True,
            )

            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["calibration"]["samples"], 2)
            self.assertEqual(result["rows_after_filter"], 2)
            self.assertTrue(calib_path.exists())
            self.assertTrue(Path(result["report_path"]).exists())
            self.assertTrue(Path(result["details_path"]).exists())


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tools.news_signal_backtest import (
    BasePriceProvider,
    SignalRecord,
    evaluate_signals,
    load_signals_from_json,
)


class MockPriceProvider(BasePriceProvider):
    def __init__(self):
        dates = pd.date_range("2026-08-01", periods=8, freq="D")
        self.price_map = {
            "600519": pd.DataFrame({"date": dates, "close": [100, 101, 103, 105, 106, 109, 111, 112]}),
            "000001": pd.DataFrame({"date": dates, "close": [50, 50.5, 50.0, 49.8, 49.3, 49.0, 48.7, 48.5]}),
            "sh000300": pd.DataFrame({"date": dates, "close": [4000, 4010, 4020, 4030, 4035, 4040, 4048, 4055]}),
        }

    def get_price_frame(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        frame = self.price_map.get(symbol)
        if frame is None:
            return pd.DataFrame(columns=["date", "close"])
        sdt = pd.to_datetime(start_date)
        edt = pd.to_datetime(end_date)
        return frame[(frame["date"] >= sdt) & (frame["date"] <= edt)].reset_index(drop=True)

    def get_index_frame(self, index_symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.get_price_frame(index_symbol, start_date, end_date)


class TestNewsSignalBacktest(unittest.TestCase):
    def test_load_signals_from_json(self):
        payload = {
            "trigger_time": "2026-08-02 09:30:00",
            "best_signals": [
                {
                    "symbol_code": "600519.SH",
                    "buy_score": 82.5,
                    "probability": "70%",
                    "action": "买入",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "signals.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)

            signals = load_signals_from_json(file_path)
            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0].symbol_code, "600519")
            self.assertAlmostEqual(signals[0].buy_score, 82.5)

    def test_evaluate_signals_with_alpha(self):
        provider = MockPriceProvider()
        signals = [
            SignalRecord(
                symbol_code="600519",
                signal_time=pd.Timestamp("2026-08-02 10:00:00").to_pydatetime(),
                buy_score=80,
                probability=0.7,
                action="buy",
                source_file="mock-a",
            ),
            SignalRecord(
                symbol_code="000001",
                signal_time=pd.Timestamp("2026-08-02 10:00:00").to_pydatetime(),
                buy_score=45,
                probability=0.55,
                action="buy",
                source_file="mock-b",
            ),
        ]

        details, summary = evaluate_signals(
            signals=signals,
            provider=provider,
            benchmark_symbol="sh000300",
            horizons=[1, 3],
        )

        self.assertEqual(len(details), 2)
        self.assertIn("ret_t1", details.columns)
        self.assertIn("alpha_t1", details.columns)
        self.assertIn("hit_rate", summary)
        self.assertEqual(summary["total_signals"], 2)
        self.assertEqual(summary["evaluated_signals"], 2)

        alpha_values = details["alpha_t1"].dropna().tolist()
        self.assertTrue(any(a > 0 for a in alpha_values))
        self.assertTrue(any(a < 0 for a in alpha_values))


if __name__ == "__main__":
    unittest.main()


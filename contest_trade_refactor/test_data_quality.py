import unittest

import pandas as pd

from utils.data_quality import validate_market_frame


class TestDataQuality(unittest.TestCase):
    def _frame(self):
        return pd.DataFrame(
            {
                "date": ["2026-08-10", "2026-08-11"],
                "open": [10.0, 10.5],
                "high": [10.5, 11.0],
                "low": [9.8, 10.2],
                "close": [10.2, 10.8],
                "volume": [1000, 1200],
            }
        )

    def test_valid_market_frame(self):
        report = validate_market_frame(self._frame(), as_of_date="2026-08-11", min_rows=2)
        self.assertTrue(report.valid)
        self.assertEqual(report.status, "ok")

    def test_future_data_is_rejected(self):
        report = validate_market_frame(self._frame(), as_of_date="2026-08-10")
        self.assertFalse(report.valid)
        self.assertIn("future_data", report.errors)

    def test_invalid_ohlc_is_rejected(self):
        frame = self._frame()
        frame.loc[1, "high"] = 9.0
        report = validate_market_frame(frame)
        self.assertFalse(report.valid)
        self.assertIn("invalid_ohlc_range", report.errors)


if __name__ == "__main__":
    unittest.main()

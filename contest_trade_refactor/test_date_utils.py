import unittest

from utils.date_utils import get_latest_completed_trading_date, normalize_trade_date_compact


class TestDateUtils(unittest.TestCase):
    def test_normalize_trade_date_compact(self):
        self.assertEqual(normalize_trade_date_compact("20260810"), "20260810")
        self.assertEqual(normalize_trade_date_compact("2026-08-10"), "20260810")

    def test_latest_completed_trading_date_uses_same_day_after_close(self):
        self.assertEqual(
            get_latest_completed_trading_date("2026-08-10 19:13:31"),
            "20260810",
        )

    def test_latest_completed_trading_date_uses_previous_day_before_close(self):
        self.assertEqual(
            get_latest_completed_trading_date("2026-08-10 14:59:59"),
            "20260807",
        )

    def test_latest_completed_trading_date_uses_previous_day_on_weekend(self):
        self.assertEqual(
            get_latest_completed_trading_date("2026-08-09 19:13:31"),
            "20260807",
        )


if __name__ == "__main__":
    unittest.main()

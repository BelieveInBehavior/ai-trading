import unittest
from unittest.mock import patch

from utils.tencent_realtime import (
    fetch_realtime_quote,
    manual_realtime_quote,
    parse_tencent_quote,
    to_tencent_code,
)


class TencentRealtimeTest(unittest.TestCase):
    def test_to_tencent_code(self):
        self.assertEqual(to_tencent_code("600519.SH"), "sh600519")
        self.assertEqual(to_tencent_code("000001"), "sz000001")
        self.assertEqual(to_tencent_code("688001"), "sh688001")

    def test_parse_tencent_quote(self):
        # Build a quote with at least 47 fields to exercise realistic Tencent gtimg format
        fields = ["1", "贵州茅台", "600519", "1500.00", "1480.00", "1490.00",
                  "123456", "70000", "50000", "1499.00", "10", "1498.00", "20",
                  "1497.00", "30", "1496.00", "40", "1495.00", "50",
                  "1501.00", "15", "1502.00", "25", "1503.00", "35",
                  "1504.00", "45", "1505.00", "55", "20260822103000",
                  "20.00", "1.35", "1520.00", "1480.00", "123456", "20000000",
                  "30", "25", "20260822103000", "20.00", "1.35", "1520.00",
                  "1480.00", "123456", "20000000", "2.5", "1505.00", "0"]
        text = 'v_sh600519="' + "~".join(fields) + '";'
        parsed = parse_tencent_quote(text)
        self.assertEqual(parsed["symbol_name"], "贵州茅台")
        self.assertEqual(parsed["price"], 1500.0)
        self.assertEqual(parsed["prev_close"], 1480.0)
        self.assertEqual(parsed["open"], 1490.0)
        self.assertGreaterEqual(len(parsed.get("bids") or []), 1)

    def test_manual_missing_returns_empty(self):
        q = manual_realtime_quote("600519.SH", manual={})
        self.assertEqual(q.source, "manual_missing")

    def test_manual_quote_used_when_tencent_fails(self):
        manual = {"symbol_code": "600519.SH", "price": 1510.0, "prev_close": 1500.0,
                  "open": 1510.0, "vwap": 1500.0, "high": 1520.0, "low": 1490.0}
        q = manual_realtime_quote("600519.SH", manual=manual)
        self.assertEqual(q.source, "manual")
        self.assertEqual(q.price, 1510.0)

    @patch("utils.tencent_realtime.fetch_tencent_quote")
    def test_fetch_realtime_auto_falls_back_to_manual(self, mock):
        from utils.tencent_realtime import RealtimeQuote
        mock.return_value = RealtimeQuote(symbol_code="sh600519", source="tencent_error")
        manual = {"symbol_code": "600519.SH", "price": 1510.0, "prev_close": 1500.0}
        q = fetch_realtime_quote("600519.SH", prefer="auto", manual=manual)
        self.assertEqual(q.source, "manual")
        self.assertEqual(q.price, 1510.0)
        self.assertIn("fallback_reason", q.detail)


if __name__ == "__main__":
    unittest.main()

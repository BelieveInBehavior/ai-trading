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
        # 按腾讯 qt 真实字段下标构造（至少 52 项），避免手工拼接导致 index 漂移
        fields = [""] * 52
        fields[0:6] = ["1", "贵州茅台", "600519", "1500.00", "1480.00", "1490.00"]
        fields[6:9] = ["123456", "70000", "50000"]
        fields[9:20] = ["1499.00", "10", "1498.00", "20", "1497.00", "30", "1496.00", "40", "1495.00", "50", "1501.00"]
        fields[30:38] = ["20260822103000", "20.00", "1.35", "1520.00", "1480.00", "1500.00/123456/185798880", "123456", "18579.888"]
        fields[49] = "1.10"
        fields[51] = "1505.00"
        text = 'v_sh600519="' + "~".join(fields) + '";'
        parsed = parse_tencent_quote(text)
        self.assertEqual(parsed["symbol_name"], "贵州茅台")
        self.assertEqual(parsed["price"], 1500.0)
        self.assertEqual(parsed["prev_close"], 1480.0)
        self.assertEqual(parsed["open"], 1490.0)
        self.assertAlmostEqual(parsed["vwap"], 1505.0, places=1)
        self.assertEqual(parsed["volume_ratio"], 1.10)
        self.assertGreaterEqual(len(parsed.get("bids") or []), 1)

    def test_parse_real_tencent_vwap_samples(self):
        samples = {
            "601919": ('v_sh601919="1~中远海控~601919~17.01~16.64~16.70~1121880~677098~444782~17.00~880~16.99~402~16.98~775~16.97~851~16.96~607~17.01~5112~17.02~4153~17.03~1416~17.04~1159~17.05~2633~~20260821161436~0.37~2.22~17.08~16.64~17.01/1121880/1898838124~1121880~189884~0.89~10.37~~17.08~16.64~2.64~2135.87~2597.11~1.13~18.30~14.98~1.10~-10958~16.93~11.05~8.41~"', 16.93),
            "688137": ('v_sh688137="1~近岸蛋白~688137~80.99~67.49~66.07~10573288~5202966~5370322~80.99~3353~80.98~213~80.97~2~80.96~6~80.90~36~0.00~0~0.00~0~0.00~0~0.00~0~0.00~0~~20260821161452~13.50~20.00~80.99~66.07~80.99/10573288/794653561~10573288~79465~15.12~-73.94~~80.99~66.07~22.11~56.63~56.63~2.80~80.99~53.99~1.55~3610~75.16~-133.50~-72.80~"', 75.16),
        }
        for sym, (text, expected_vwap) in samples.items():
            parsed = parse_tencent_quote(text)
            self.assertAlmostEqual(parsed["vwap"], expected_vwap, places=2, msg=sym)
            self.assertTrue(0.5 * parsed["price"] <= parsed["vwap"] <= 2.0 * parsed["price"], msg=sym)

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

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.signal_schema import parse_json_signals, validate_research_signal
from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine


class CatalystStructuredSchemaTest(unittest.TestCase):
    def test_new_structured_catalyst_preserved(self):
        signals = parse_json_signals('''{
          "signals": [{
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600519.SH",
            "symbol_name": "贵州茅台",
            "event_type": "earnings_surprise",
            "event_date": "2026-08-15",
            "event_summary": "中报预增",
            "event_level": "A",
            "freshness": 0.1,
            "company_specific": true,
            "credibility": 0.9,
            "source_quality": "公告",
            "earnings_impact": 0.8,
            "expected_return_pct": 3.0,
            "actual_return_pct": 4.2,
            "gap_pct": 1.5,
            "intraday_return_pct": 1.2,
            "price_reaction": "positive",
            "price_in_status": "not yet visible",
            "evidence_list": [{"description": "公告落地"}],
            "limitations": [],
            "probability": 0.72
          }]
        }''')
        self.assertEqual(len(signals), 1)
        sig = signals[0]
        self.assertEqual(sig["event_level"], "A")
        self.assertGreater(sig["credibility"], 0.8)
        self.assertEqual(sig["price_reaction"], "positive")
        self.assertEqual(sig["source_quality"], "公告")

    def test_legacy_catalyst_certainty_backfills_event_level_and_credibility(self):
        sig = validate_research_signal({
            "symbol_code": "000001.SZ",
            "symbol_name": "平安银行",
            "event_type": "order_win",
            "catalyst_certainty": 8.5,
            "catalyst_market_impact": 7.0,
            "price_in_status": "not yet visible",
        })
        self.assertEqual(sig["event_level"], "A")  # (8.5+7)/2=7.75 -> A
        self.assertAlmostEqual(sig["credibility"], 0.85)
        self.assertGreaterEqual(sig["earnings_impact"], 0.7)
        self.assertEqual(sig["price_reaction"], "positive")

    def test_no_catalyst_zeroes_structured(self):
        sig = validate_research_signal({
            "has_opportunity": "yes",
            "symbol_code": "300001.SZ",
            "symbol_name": "测试",
            "event_type": None,
        })
        self.assertFalse(sig["event_level"])
        self.assertEqual(sig["credibility"], 0.0)
        self.assertEqual(sig["price_reaction"], "neutral")

    def test_engine_assess_catalyst_reads_new_structured_output(self):
        eng = MainTrendEngine(MainTrendConfig.from_yaml())
        factor = {
            "catalyst": {
                "event_type": "earnings_surprise",
                "event_level": "S",
                "freshness": 0.1,
                "company_specific": True,
                "credibility": 0.95,
                "source_quality": "官方",
                "earnings_impact": 0.8,
                "expected_return_pct": 3.0,
                "actual_return_pct": 8.0,
            },
            "change_pct": 8.0,
        }
        c = eng.assess_catalyst(factor)
        self.assertTrue(c.has_event)
        self.assertGreater(c.score, 70)
        self.assertIn("实际/预期收益=2.67", c.reasons)


if __name__ == "__main__":
    unittest.main()

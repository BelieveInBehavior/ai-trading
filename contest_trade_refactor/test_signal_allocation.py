import unittest

import pandas as pd

from agents.market_regime_detector import MarketRegimeDetector
from agents.signal_tier_classifier import SignalTierClassifier


class TestSignalTierClassifier(unittest.TestCase):
    def _signal(self, score=85, edge=1.0, quality=80, downside=4, passed=True):
        return {
            "symbol_code": "600001.SH",
            "buy_score": score,
            "expected_net_edge_pct": edge,
            "expected_downside_pct": downside,
            "probability_value": 0.65,
            "risk_flags": [],
            "next_day_factor_scorecard": {
                "forward_opportunity_score": score,
                "data_quality_score": quality,
            },
            "next_day_gate_report": {"passed": passed, "failed_reasons": []},
        }

    def test_high_forward_edge_is_tier_a_without_legacy_trend_gate(self):
        tiers = SignalTierClassifier().classify([self._signal()], "bull")
        self.assertEqual(len(tiers["tier_A"]), 1)
        self.assertGreater(tiers["tier_A"][0]["recommended_position_size_pct"], 0)

    def test_position_shrinks_with_volatility_and_bear_regime(self):
        classifier = SignalTierClassifier()
        calm = classifier.classify([self._signal(downside=2)], "bull")["tier_A"][0]
        volatile = classifier.classify([self._signal(downside=8)], "bear")["tier_A"][0]
        self.assertGreater(
            calm["recommended_position_size_pct"],
            volatile["recommended_position_size_pct"],
        )

    def test_risk_veto_and_low_quality_reject(self):
        risky = self._signal()
        risky["risk_flags"] = ["立案调查"]
        low_quality = self._signal(quality=20)
        tiers = SignalTierClassifier().classify([risky, low_quality])
        self.assertEqual(len(tiers["tier_reject"]), 2)


class TestMarketRegimeDetector(unittest.TestCase):
    def test_bull_and_bear_are_driven_by_price_and_breadth(self):
        detector = MarketRegimeDetector()
        bull_prices = pd.DataFrame({"close": list(range(100, 125))})
        bear_prices = pd.DataFrame({"close": list(range(125, 100, -1))})
        bull, _, _ = detector.detect(
            {"advance_ratio": 0.75, "limit_up_down_ratio": 3, "risk_sentiment": "risk_on"},
            bull_prices,
        )
        bear, _, _ = detector.detect(
            {"advance_ratio": 0.25, "limit_up_down_ratio": 0.4, "risk_sentiment": "risk_off"},
            bear_prices,
        )
        self.assertEqual(bull, "bull")
        self.assertEqual(bear, "bear")

    def test_missing_inputs_fall_back_to_neutral(self):
        regime, confidence, reasons = MarketRegimeDetector().detect({})
        self.assertEqual(regime, "neutral")
        self.assertEqual(confidence, 50.0)
        self.assertTrue(reasons)


if __name__ == "__main__":
    unittest.main()

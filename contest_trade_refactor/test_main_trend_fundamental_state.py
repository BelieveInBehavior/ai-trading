import unittest

from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.schemas import Holding


class MainTrendFundamentalStateTest(unittest.TestCase):
    def setUp(self):
        self.engine = MainTrendEngine(MainTrendConfig())

    def test_future_announcement_is_ignored(self):
        state = self.engine.assess_fundamental_state(
            {
                "financial_ann_date": "20260828",
                "financial_report_revenue_yoy": 40,
                "financial_report_net_profit_yoy": 80,
            },
            "20260827",
        )
        self.assertEqual(state.state, "FU")
        self.assertFalse(state.available)
        self.assertIn("POINT_IN_TIME_GUARD", state.risk_flags)

    def test_quality_growth_is_f1(self):
        state = self.engine.assess_fundamental_state(
            {
                "financial_ann_date": "20260826",
                "financial_report_revenue_yoy": 25,
                "adjusted_net_profit_yoy": 35,
                "roe_ttm": 14,
                "ocf_to_net_profit": 1.1,
                "debt_ratio": 38,
            },
            "20260827",
        )
        self.assertEqual(state.state, "F1")
        self.assertTrue(state.passed)

    def test_s0_and_f4_reduce_without_waiting_two_days(self):
        holding = Holding(
            symbol_code="600000.SH",
            symbol_name="test",
            entry_date="20260826",
            entry_price=10,
            current_price=10.2,
            highest_price=10.2,
            highest_close=10.2,
            ma10=10.0,
            ma20=9.8,
            trend_state="S0",
            previous_trend_state="S1",
            trend_state_streak=1,
            fundamental_state="F4",
            fundamental_state_info={"state": "F4", "risk_flags": ["WEAK_CASH_CONVERSION"]},
        )
        decision = self.engine.evaluate_exits([holding])[0]
        self.assertEqual(decision.action, "reduce")
        self.assertGreaterEqual(decision.reduce_pct, 50)
        self.assertEqual(decision.fundamental_state, "F4")

    def test_good_fundamentals_do_not_override_price_break(self):
        holding = Holding(
            symbol_code="600000.SH",
            symbol_name="test",
            entry_date="20260820",
            entry_price=10,
            current_price=9.5,
            highest_price=11,
            highest_close=11,
            ma10=10.2,
            ma20=10.0,
            trend_state="S1",
            fundamental_state="F1",
            fundamental_state_info={"state": "F1"},
        )
        decision = self.engine.evaluate_exits([holding])[0]
        self.assertEqual(decision.action, "exit")
        self.assertIn("MA20", decision.reason)


if __name__ == "__main__":
    unittest.main()

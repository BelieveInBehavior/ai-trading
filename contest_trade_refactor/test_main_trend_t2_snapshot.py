import unittest

from scripts.main_trend_holdings import to_holding_dict
from scripts.main_trend_t2_snapshot import seed_previous_day_guards
from strategies.main_trend.holdings import compute_display_status
from strategies.main_trend.schemas import Holding


class MainTrendT2SnapshotTest(unittest.TestCase):
    def test_seed_previous_day_guards_from_source_close_quote(self):
        rows = [{
            "symbol_code": "601069",
            "trade_plan": {},
            "realtime_quote": {"vwap": 32.7137, "high": 34.56},
        }]
        seeded = seed_previous_day_guards(rows)[0]
        self.assertEqual(seeded["trade_plan"]["next_day_guard_vwap"], 32.7137)
        self.assertEqual(seeded["trade_plan"]["next_day_guard_high"], 34.56)

    def test_refreshed_ma10_is_serialized(self):
        holding = Holding(
            symbol_code="000001",
            symbol_name="测试",
            entry_date="20260824",
            entry_price=10.0,
            ma10=9.8,
        )
        self.assertEqual(to_holding_dict(holding)["ma10"], 9.8)

    def test_trend_transition_memory_is_serialized(self):
        holding = Holding(
            symbol_code="000001", symbol_name="测试", entry_date="20260824", entry_price=10.0,
            trend_state="S0", previous_trend_state="S1", trend_state_streak=1,
            trend_state_as_of="20260825", trend_state_changed_at="20260825",
            trend_reason_code="NORMAL_PULLBACK", trend_confidence=0.55,
        )
        row = to_holding_dict(holding)
        self.assertEqual(row["previous_trend_state"], "S1")
        self.assertEqual(row["trend_state_streak"], 1)
        self.assertEqual(row["trend_reason_code"], "NORMAL_PULLBACK")

    def test_decay_has_distinct_display_status(self):
        self.assertEqual(
            compute_display_status({"position_state": "DECAY", "exit_action": "decay"}),
            "DECAY",
        )

    def test_watch_has_distinct_display_status(self):
        self.assertEqual(
            compute_display_status({"position_state": "WATCH", "exit_action": "hold"}),
            "WATCH",
        )


if __name__ == "__main__":
    unittest.main()

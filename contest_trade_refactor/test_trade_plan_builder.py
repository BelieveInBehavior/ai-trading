"""Tests for the candidate-level trade plan builder and portfolio integration helpers."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.trade_plan_builder import (
    build_trade_plan,
    attach_trade_plans,
    format_trade_plan_markdown,
)


class TradePlanBuilderTest(unittest.TestCase):
    def test_build_plan_bad_symbol(self):
        plan = build_trade_plan("abc", trade_date="20260814")
        self.assertEqual(plan.get("status"), "error")
        self.assertEqual(plan.get("error"), "invalid_symbol")

    def test_attach_trade_plans(self):
        sig = {"symbol_code": "600519", "symbol_name": "贵州茅台", "buy_decision": "buy"}
        out = attach_trade_plans([sig], trade_date="20260814")
        self.assertEqual(len(out), 1)
        self.assertIn("trade_plan", out[0])
        plan = out[0]["trade_plan"]
        # It may be ok or error depending on data connectivity; just ensure structure present.
        self.assertTrue(isinstance(plan, dict))
        self.assertIn("status", plan)

    def test_format_trade_plan_markdown(self):
        plan = {
            "status": "ok",
            "indicators": {"rsi": 60, "vwap_20": 100.0, "ema8": 99.0, "ema13": 98.0, "ema21": 97.0, "volume_ratio": 1.1},
            "levels": {"support_1": 95.0, "support_2": 93.0, "resistance_1": 105.0, "resistance_2": 108.0},
            "plan": {"entry_zone_low": 99.0, "entry_zone_high": 100.0, "stop_loss": 94.0, "stop_loss_pct": -4.5, "take_profit_1": 105.0, "take_profit_2": 108.0, "rr_1": 1.5, "suggested_position_size_pct": 5.0},
            "risk": {},
        }
        text = format_trade_plan_markdown(plan)
        self.assertIn("支撑1/2=95.0/93.0", text)
        self.assertIn("止损=94.0(-4.5%)", text)
        self.assertIn("仓位建议=5.0%", text)


if __name__ == "__main__":
    unittest.main()

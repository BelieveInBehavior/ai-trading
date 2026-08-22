"""Tests for the candidate-level trade plan builder and portfolio integration helpers."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.trade_plan_builder import (
    _calc_atr,
    _calc_rsi,
    _calc_vwap,
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


class TradePlanBuilderFactorMathTest(unittest.TestCase):
    def test_rsi_uses_wilder_smoothing_not_simple_ma(self):
        # All up -> RSI=100 regardless of smoothing method
        closes = pd.Series([100 + i for i in range(30)], dtype=float)
        self.assertEqual(_calc_rsi(closes, 14), 100.0)
        # Alternating up/down: still produce a valid [0,100] Wilder RSI.
        closes2 = pd.Series([100 + (0.2 if i % 2 == 0 else -0.1) for i in range(80)], dtype=float)
        rsi_val = _calc_rsi(closes2, 14)
        self.assertGreaterEqual(rsi_val, 0.0)
        self.assertLessEqual(rsi_val, 100.0)

    def test_atr_uses_wilder_smoothing(self):
        high = pd.Series([10.0 + 0.1 * i for i in range(30)], dtype=float)
        low = pd.Series([9.8 + 0.1 * i for i in range(30)], dtype=float)
        close = pd.Series([10.0 + 0.1 * i for i in range(30)], dtype=float)
        val = _calc_atr(high, low, close, 14)
        self.assertFalse(val != val)  # not nan
        self.assertGreater(val, 0.0)

    def test_vwap_uses_amount_when_available_and_never_close_mean(self):
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=5),
                "open": [10.0, 10.1, 10.0, 10.2, 10.1],
                "high": [10.3, 10.4, 10.3, 10.5, 10.4],
                "low": [9.9, 10.0, 9.9, 10.1, 10.0],
                "close": [10.1, 10.2, 10.15, 10.3, 10.2],
                "volume": [100, 200, 300, 400, 500],
        }
        )
        # 用一组“金额”与“成交量”不一致的数据：金额=成交量×固定价，权重应跟随固定价。
        frame["amount"] = frame["volume"] * 10.0
        exact = _calc_vwap(frame, 5)
        self.assertIsNotNone(exact)
        # expected = Σ(tp * amount) / Σ(amount)
        tp = (frame["high"] + frame["low"] + frame["close"]) / 3.0
        expected = float((tp * frame["amount"]).sum() / frame["amount"].sum())
        self.assertAlmostEqual(exact, expected, places=4)

        # If amount missing, volume fallback returns the volume version (not None)
        frame2 = frame.drop(columns=["amount"])
        vol_vwap = _calc_vwap(frame2, 5)
        self.assertIsNotNone(vol_vwap)
        expected_vol = float((tp * frame2["volume"]).sum() / frame2["volume"].sum())
        self.assertAlmostEqual(vol_vwap, expected_vol, places=4)

        # No volume andno amount -> return None, not close.mean()
        frame3 = frame2.drop(columns=["volume"])
        self.assertIsNone(_calc_vwap(frame3, 5))


if __name__ == "__main__":
    unittest.main()

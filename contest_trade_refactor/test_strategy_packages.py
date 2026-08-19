"""Tests for strategy packages (strategies/<name>/) and unified backtest CLI helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.strategies import get_strategy, get_strategies
from scripts.strategy_backtest import (
    _horizons,
    _history,
    _symbols_limit,
    _concurrency,
)


class StrategyPackagesTest(unittest.TestCase):
    def test_package_fields_loaded(self):
        for name in ("momentum", "swing"):
            cfg = get_strategy(name)
            self.assertEqual(cfg.get("id"), name)
            self.assertIn("name", cfg)
            self.assertIsInstance(cfg.get("belief_list"), list)
            self.assertGreaterEqual(len(cfg["belief_list"]), 1)
            self.assertIn("backtest", cfg)
            self.assertIn("tool_list", cfg)

    def test_tool_list_from_package(self):
        m = get_strategy("momentum")
        self.assertTrue(m.get("tool_list"))
        self.assertIn("tools.final_report.final_report", m["tool_list"])

    def test_get_strategies_contains_packages(self):
        ids = [s.get("id") for s in get_strategies()]
        self.assertIn("momentum", ids)
        self.assertIn("swing", ids)

    def test_backtest_defaults_from_package(self):
        m = get_strategy("momentum")
        self.assertEqual(_horizons(m), (1, 3, 5))
        self.assertEqual(_symbols_limit(m, None), 0)
        self.assertEqual(_concurrency(m, None), 4)
        self.assertIsInstance(_history(m, "", ""), tuple)

    def test_strategy_backtest_script_compiles(self):
        script = PROJECT_ROOT / "scripts" / "strategy_backtest.py"
        self.assertTrue(script.exists())
        import py_compile
        py_compile.compile(str(script), doraise=True)


if __name__ == "__main__":
    unittest.main()

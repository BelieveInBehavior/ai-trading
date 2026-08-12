import unittest
from unittest.mock import AsyncMock, patch

from main_loop import SimpleTradeCompany


class TestSignalSelectionLoop(unittest.TestCase):
    def test_get_signal_selection_settings_defaults(self):
        company = SimpleTradeCompany()
        with patch.object(
            type(company),
            "_get_signal_selection_settings",
            wraps=company._get_signal_selection_settings,
        ):
            require_min, max_rounds = company._get_signal_selection_settings()
        self.assertGreaterEqual(require_min, 0)
        self.assertGreaterEqual(max_rounds, 1)

    def test_run_once_when_require_min_buys_zero(self):
        async def _run():
            company = SimpleTradeCompany()
            calls = {"count": 0}

            async def fake_research(_trigger_time, _data_factors):
                calls["count"] += 1
                return [
                    {
                        "has_opportunity": "是",
                        "action": "买入",
                        "symbol_code": "600519.SH",
                        "symbol_name": "贵州茅台",
                        "probability": "80%",
                        "evidence_list": [],
                        "limitations": [],
                    }
                ]

            with patch.object(company, "_get_signal_selection_settings", return_value=(0, 3)):
                with patch.object(company, "_run_research_agents", side_effect=fake_research):
                    with patch.object(
                        company,
                        "_select_signal_groups",
                        return_value={"buy_signals": [], "watchlist": []},
                    ):
                        result = await company._run_research_and_select_until_min_buys(
                            trigger_time="2026-08-11 10:00:00",
                            data_factors=[],
                            market_context={},
                            research_runner=fake_research,
                        )

            self.assertEqual(calls["count"], 1)
            self.assertEqual(result["research_rounds"], 1)
            self.assertTrue(result["require_min_buys_met"])

        import asyncio

        asyncio.run(_run())

    def test_stops_when_min_buys_met(self):
        async def _run():
            company = SimpleTradeCompany()
            calls = {"count": 0}

            async def fake_research(_trigger_time, _data_factors):
                calls["count"] += 1
                return [{"symbol_code": "000001.SZ", "symbol_name": "平安银行"}]

            def fake_select(research_signals, trigger_time, market_context, system_health):
                buy_count = 1 if calls["count"] >= 2 else 0
                return {
                    "buy_signals": [{"symbol_code": "x"}] if buy_count else [],
                    "watchlist": [],
                }

            with patch.object(company, "_get_signal_selection_settings", return_value=(1, 5)):
                with patch.object(company, "_select_signal_groups", side_effect=fake_select):
                    with patch(
                        "main_loop._enrich_signals_with_technical_factors",
                        side_effect=lambda signals, *_args, **_kwargs: signals,
                    ):
                        result = await company._run_research_and_select_until_min_buys(
                            trigger_time="2026-08-11 10:00:00",
                            data_factors=[],
                            market_context={},
                            research_runner=fake_research,
                        )

            self.assertEqual(calls["count"], 2)
            self.assertEqual(result["research_rounds"], 2)
            self.assertTrue(result["require_min_buys_met"])
            self.assertEqual(len(result["buy_signals"]), 1)

        import asyncio

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

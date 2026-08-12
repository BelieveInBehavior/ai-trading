import json
import unittest

from utils.report_utils import generate_trade_decision_report


class TestTradeDecisionReport(unittest.TestCase):
    def test_generate_trade_decision_report_outputs_files(self):
        result = {
            "trigger_time": "2026-08-08 20:19:46",
            "research_signals": [{"symbol_code": "600519.SH"}],
            "consensus_signals": [{"symbol_code": "600519.SH"}],
            "best_signals": [
                {
                    "symbol_code": "600519.SH",
                    "symbol_name": "贵州茅台",
                    "buy_score": 78.2,
                    "probability_value": 0.72,
                    "expected_return_t1_pct": 1.15,
                    "buy_decision": "buy",
                    "signal_contract_version": "buy-signal.v1",
                    "entry_timing": "next_trading_day_open",
                    "analysis_as_of_date": "2026-08-08",
                    "risk_flags": [],
                    "next_day_gate_report": {"passed": True, "failed_reasons": []},
                }
            ],
            "market_context": {
                "market_trend": "up",
                "risk_sentiment": "risk_on",
                "has_sector_flow_data": True,
            },
            "system_health": {"tool_error_count": 0},
        }

        path = generate_trade_decision_report(result)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

        json_path = path.with_suffix(".json")
        self.assertTrue(json_path.exists())
        content = path.read_text(encoding="utf-8")
        self.assertIn("`signal_contract_version`: `buy-signal.v1`", content)
        self.assertIn("`entry_timing`: `next_trading_day_open`", content)
        self.assertIn("`analysis_as_of_date`: `2026-08-08`", content)
        self.assertIn("`risk_flags`: `none`", content)
        self.assertIn("共识标的数", content)

        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        self.assertEqual(payload["trigger_time"], result["trigger_time"])
        self.assertEqual(payload["best_signals"][0]["symbol_code"], "600519.SH")

    def test_watchlist_is_not_rendered_as_buy_list(self):
        result = {
            "trigger_time": "2026-08-08 20:20:46",
            "research_signals": [{"symbol_code": "300502.SZ"}],
            "buy_signals": [],
            "watchlist": [
                {
                    "symbol_code": "300502.SZ",
                    "symbol_name": "新易盛",
                    "buy_score": 96.73,
                    "probability_value": 0.5636,
                    "expected_return_t1_pct": 0.632,
                    "buy_decision": "watch",
                    "technical_factor": {
                        "report_date": "20260810",
                        "close": 399.6,
                        "change_pct": -5.07,
                        "ma20_deviation_pct": -14.0,
                        "rsi": 29.3,
                        "macd": -7.021,
                        "volume_ratio": 1.08,
                        "bollinger": "中下",
                    },
                    "next_day_gate_report": {
                        "passed": False,
                        "failed_reasons": ["risk_reward<50.0", "data_quality<45.0"],
                    },
                }
            ],
            "best_signals": [],
            "market_context": {},
            "system_health": {},
        }

        path = generate_trade_decision_report(result)
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("无满足次日买入门槛的标的。", content)
        self.assertIn("观察清单", content)
        self.assertIn("新易盛", content)
        self.assertIn("MA20距离-14.00%", content)
        self.assertIn("RSI=29.30", content)
        buy_section = content.split("## 观察清单", 1)[0]
        self.assertNotIn("### 1. 新易盛", buy_section)

    def test_empty_research_is_reported_as_upstream_issue(self):
        result = {
            "trigger_time": "2026-08-11 13:53:00",
            "research_signals": [],
            "buy_signals": [],
            "watchlist": [],
            "best_signals": [],
            "market_context": {},
            "system_health": {
                "agent_error_count": 1,
                "warnings": ["agent_0_empty_final_result"],
            },
        }

        path = generate_trade_decision_report(result)
        content = path.read_text(encoding="utf-8")
        self.assertIn("研究 Agent 未产生可解析信号", content)
        self.assertIn("agent_0_empty_final_result", content)
        self.assertNotIn("无满足次日买入门槛的标的。", content)

    def test_empty_quantitative_screen_is_reported_separately(self):
        result = {
            "trigger_time": "2026-08-11 14:00:00",
            "research_signals": [],
            "buy_signals": [],
            "watchlist": [],
            "best_signals": [],
            "quantitative_screen": {
                "status": "ok",
                "universe_count": 5000,
                "scanned_count": 4900,
                "passed_count": 0,
            },
            "quantitative_candidates": [],
            "market_context": {},
            "system_health": {},
        }

        path = generate_trade_decision_report(result)
        content = path.read_text(encoding="utf-8")
        self.assertIn("没有股票通过全市场周线、相对强度和日线预筛选", content)
        self.assertNotIn("研究 Agent 未产生可解析信号", content)


if __name__ == "__main__":
    unittest.main()

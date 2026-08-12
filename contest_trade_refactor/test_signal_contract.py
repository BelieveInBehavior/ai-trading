import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agents.signal_schema import parse_json_signals, validate_buy_decision
from agents.stock_opportunity_ranker import RankerConfig, StockOpportunityRanker
from main_loop import SimpleTradeCompany


class TestSignalContract(unittest.TestCase):
    def test_json_signal_is_normalized(self):
        signals = parse_json_signals(
            """
            {
              "signals": [{
                "has_opportunity": "yes",
                "action": "buy",
                "symbol_code": "600519.SH",
                "symbol_name": "贵州茅台",
                "evidence_list": [{
                  "description": "公司公告回购",
                  "time": "2026-08-11 09:30:00",
                  "from_source": "公司公告"
                }],
                "limitations": ["短期波动"],
                "probability": "72%"
              }]
            }
            """
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol_code"], "600519.SH")
        self.assertAlmostEqual(signals[0]["probability"], 0.72)
        self.assertEqual(signals[0]["evidence_list"][0]["from_source"], "公司公告")

    def test_structured_reasoning_is_used_when_visible_output_is_empty(self):
        company = object.__new__(SimpleTradeCompany)
        result = SimpleNamespace(
            final_result="",
            final_result_thinking="""
            The provider returned the structured answer in reasoning:
            {"signals": [{
              "has_opportunity": "yes",
              "action": "buy",
              "symbol_code": "600519.SH",
              "symbol_name": "贵州茅台",
              "evidence_list": [{
                "description": "公司公告回购",
                "time": "2026-08-11 09:30:00",
                "from_source": "公司公告"
              }],
              "limitations": ["短期波动"],
              "probability": 0.72
            }]}
            """,
        )

        with patch(
            "main_loop.GLOBAL_MARKET_MANAGER.fix_symbol_code",
            return_value=("贵州茅台", "600519.SH"),
        ):
            signals = company._parse_signals(result)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol_code"], "600519.SH")

    def test_legacy_xml_signal_still_parses(self):
        company = object.__new__(SimpleTradeCompany)
        result = SimpleNamespace(
            final_result_thinking="reasoning",
            final_result="""
            <signals>
              <signal>
                <has_opportunity>yes</has_opportunity>
                <action>buy</action>
                <symbol_code>600519.SH</symbol_code>
                <symbol_name>贵州茅台</symbol_name>
                <evidence_list>
                  <evidence>公司公告回购
                    <time>2026-08-11 09:30:00</time>
                    <from_source>公司公告</from_source>
                  </evidence>
                </evidence_list>
                <limitations><limitation>短期波动</limitation></limitations>
                <probability>72%</probability>
              </signal>
            </signals>
            """,
        )

        with patch(
            "main_loop.GLOBAL_MARKET_MANAGER.fix_symbol_code",
            return_value=("贵州茅台", "600519.SH"),
        ):
            signals = company._parse_signals(result)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol_name"], "贵州茅台")
        self.assertAlmostEqual(signals[0]["probability"], 0.72)

    def test_future_evidence_cannot_pass_buy_gates(self):
        ranker = StockOpportunityRanker(
            RankerConfig(
                min_buy_score=0,
                min_probability=0,
                min_tradeability_score=0,
                min_risk_reward_score=0,
                min_data_quality_score=0,
                min_technical_score=0,
                expected_return_floor_pct=-10,
                max_prev_day_gain_pct=100,
                max_ma20_deviation_pct=100,
                enforce_flow_confirmation_if_available=False,
            )
        )
        signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600519.SH",
            "symbol_name": "贵州茅台",
            "probability": 0.8,
            "evidence_list": [
                {
                    "description": "公司公告回购",
                    "time": "2026-08-11 09:00:00",
                    "from_source": "公司公告",
                },
                {
                    "description": "未来收盘后才发布的消息",
                    "time": "2026-08-11 11:00:00",
                    "from_source": "公司公告",
                },
            ],
            "limitations": [],
        }

        scored = ranker.score_signals([signal], "2026-08-11 10:00:00")
        item = scored[0]
        self.assertEqual(item["next_day_factor_scorecard"]["future_evidence_count"], 1)
        self.assertFalse(item["next_day_gate_report"]["passed"])
        self.assertIn("evidence_after_analysis>1", item["next_day_gate_report"]["failed_reasons"])
        self.assertIn("future_evidence", item["risk_flags"])

    def test_hard_risk_is_vetoed_and_contract_is_present(self):
        ranker = StockOpportunityRanker(
            RankerConfig(
                min_buy_score=0,
                min_probability=0,
                min_tradeability_score=0,
                min_risk_reward_score=0,
                min_data_quality_score=0,
                min_technical_score=0,
                expected_return_floor_pct=-10,
                enforce_flow_confirmation_if_available=False,
            )
        )
        signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "000001.SZ",
            "symbol_name": "平安银行",
            "probability": 0.8,
            "evidence_list": [{
                "description": "公司涉嫌财务造假，存在重大风险",
                "time": "2026-08-11 09:00:00",
                "from_source": "公司公告",
            }],
            "limitations": [],
        }

        item = ranker.score_signals([signal], "2026-08-11 10:00:00")[0]
        self.assertEqual(item["signal_contract_version"], "buy-signal.v1")
        self.assertEqual(item["entry_timing"], "next_trading_day_open")
        self.assertFalse(item["risk_veto_report"]["passed"])
        self.assertIn("hard_risk:财务造假", item["risk_veto_report"]["reasons"])
        self.assertIn("risk_veto:hard_risk:财务造假", item["next_day_gate_report"]["failed_reasons"])

    def test_buy_decision_contract_keeps_metadata(self):
        decision = validate_buy_decision({
            "symbol_code": "600519.SH",
            "symbol_name": "贵州茅台",
            "buy_decision": "buy",
            "buy_score": 81.2,
            "probability_value": "72%",
            "risk_flags": ["future_evidence"],
            "analysis_as_of_date": "2026-08-11",
        })

        self.assertEqual(decision["signal_contract_version"], "buy-signal.v1")
        self.assertAlmostEqual(decision["probability_value"], 0.72)
        self.assertEqual(decision["analysis_as_of_date"], "2026-08-11")


if __name__ == "__main__":
    unittest.main()

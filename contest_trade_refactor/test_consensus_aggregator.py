import unittest

from agents.consensus_aggregator import ConsensusAggregator, ConsensusConfig
from agents.stock_opportunity_ranker import RankerConfig, StockOpportunityRanker


def _signal(agent_id, action, probability, research_round=1, description="基本面改善"):
    return {
        "agent_id": agent_id,
        "agent_name": agent_id,
        "research_round": research_round,
        "has_opportunity": "yes" if action == "buy" else "no",
        "action": action,
        "symbol_code": "600519.SH",
        "symbol_name": "贵州茅台",
        "probability": probability,
        "evidence_list": [{
            "description": description,
            "time": "2026-08-11 09:00:00",
            "from_source": "公司公告",
        }],
        "limitations": [],
        "data_quality_warnings": [],
    }


class TestConsensusAggregator(unittest.TestCase):
    def test_repeated_rounds_from_one_agent_count_once(self):
        aggregator = ConsensusAggregator()
        signals = [
            _signal("agent_0", "buy", 0.80, research_round=1),
            _signal("agent_0", "buy", 0.82, research_round=2, description="订单增长"),
            _signal("agent_1", "buy", 0.72),
            _signal("agent_2", "watch", 0.60),
        ]

        aggregated = aggregator.aggregate(signals, "2026-08-11 10:00:00")
        self.assertEqual(len(aggregated), 1)
        item = aggregated[0]
        report = item["consensus_report"]

        self.assertEqual(report["source_signal_count"], 4)
        self.assertEqual(report["agent_count"], 3)
        self.assertEqual(report["buy_vote_count"], 2)
        self.assertEqual(report["watch_vote_count"], 1)
        self.assertEqual(report["consensus_action"], "buy")
        self.assertTrue(report["passed"])
        self.assertEqual(item["supporting_signal_count"], 3)
        self.assertEqual(len(item["agent_votes"]), 3)
        self.assertTrue(all("agent_id" in evidence for evidence in item["evidence_list"]))

    def test_tied_votes_become_watch(self):
        aggregator = ConsensusAggregator(
            ConsensusConfig(require_majority=True)
        )
        aggregated = aggregator.aggregate(
            [
                _signal("agent_0", "buy", 0.70),
                _signal("agent_1", "watch", 0.70),
            ],
            "2026-08-11 10:00:00",
        )

        report = aggregated[0]["consensus_report"]
        self.assertEqual(report["buy_vote_count"], 1)
        self.assertEqual(report["watch_vote_count"], 1)
        self.assertEqual(report["consensus_action"], "watch")
        self.assertFalse(report["passed"])
        self.assertEqual(aggregated[0]["action"], "watch")

    def test_ranker_uses_consensus_confidence_as_score_component(self):
        aggregator = ConsensusAggregator()
        signal = aggregator.aggregate(
            [
                _signal("agent_0", "buy", 0.85),
                _signal("agent_1", "buy", 0.75),
                _signal("agent_2", "watch", 0.55),
            ],
            "2026-08-11 10:00:00",
        )[0]

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
        scored = ranker.score_signals([signal], "2026-08-11 10:00:00")[0]
        self.assertGreater(scored["next_day_factor_scorecard"]["consensus_score"], 0)
        self.assertEqual(scored["consensus_report"]["consensus_action"], "buy")
        self.assertEqual(scored["supporting_signal_count"], 3)


if __name__ == "__main__":
    unittest.main()

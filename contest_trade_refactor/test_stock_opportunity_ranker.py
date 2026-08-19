import unittest

from agents.stock_opportunity_ranker import RankerConfig, StockOpportunityRanker


class TestStockOpportunityRanker(unittest.TestCase):
    def test_forward_score_does_not_saturate_at_100(self):
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
            "symbol_code": "600001.SH",
            "symbol_name": "前瞻机会",
            "probability": "80%",
            "technical_factor": {
                "weekly_data_available": True,
                "weekly_trend_score": 90,
                "relative_strength_available": True,
                "relative_strength_score": 90,
                "daily_entry_score": 75,
                "ma20_deviation_pct": 3,
                "rsi": 55,
                "volume_ratio": 1.3,
                "macd": 1.0,
            },
            "evidence_list": [
                {
                    "description": "公司公告新增订单超预期，主力资金净流入",
                    "time": "2026-08-11 09:30:00",
                    "from_source": "公司公告",
                }
            ],
            "limitations": [],
        }

        scored = ranker.score_signals([signal], "2026-08-11 10:00:00")[0]

        self.assertLess(scored["buy_score"], 100)
        self.assertEqual(
            scored["buy_score"],
            scored["next_day_factor_scorecard"]["forward_opportunity_score"],
        )

    def test_flow_is_soft_when_hard_confirmation_is_disabled(self):
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
            "symbol_code": "600002.SH",
            "symbol_name": "催化启动",
            "probability": "70%",
            "evidence_list": [
                {
                    "description": "新增订单超预期，但暂未见明显资金净流入",
                    "time": "2026-08-11 09:30:00",
                    "from_source": "公司公告",
                }
            ],
            "limitations": [],
        }

        scored = ranker.score_signals(
            [signal],
            "2026-08-11 10:00:00",
            market_context={"has_sector_flow_data": True},
        )[0]

        self.assertNotIn("flow<", " ".join(scored["next_day_gate_report"]["failed_reasons"]))

    def test_rank_signals_prefers_high_quality_buy_signal(self):
        ranker = StockOpportunityRanker(
            RankerConfig(top_k=5, min_buy_score=55, min_probability=0.5)
        )
        trigger_time = "2026-08-08 10:00:00"

        signals = [
            {
                "has_opportunity": "是",
                "action": "买入",
                "symbol_code": "600519.SH",
                "symbol_name": "贵州茅台",
                "probability": "78%",
                "evidence_list": [
                    {
                        "description": "公司公告回购并上修全年指引，订单增长超预期",
                        "time": "2026-08-08 09:20:00",
                        "from_source": "公司公告",
                    },
                    {
                        "description": "机构上调目标价",
                        "time": "2026-08-08 08:50:00",
                        "from_source": "上交所",
                    },
                ],
                "limitations": ["短期波动仍需跟踪"],
            },
            {
                "has_opportunity": "是",
                "action": "卖出",
                "symbol_code": "000001.SZ",
                "symbol_name": "平安银行",
                "probability": "80%",
                "evidence_list": [
                    {
                        "description": "盈利承压并出现风险事件",
                        "time": "2026-08-08 09:10:00",
                        "from_source": "论坛传闻",
                    }
                ],
                "limitations": [],
            },
        ]

        ranked = ranker.rank_signals(signals, trigger_time)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["symbol_code"], "600519.SH")
        self.assertGreaterEqual(ranked[0]["buy_score"], 55)
        self.assertIn("next_day_factor_scorecard", ranked[0])
        self.assertIn("next_day_gate_report", ranked[0])
        self.assertIn("expected_return_t1_pct", ranked[0])
        self.assertTrue(ranked[0]["next_day_gate_report"]["passed"])

    def test_numeric_pct_fields_are_already_percentage_points(self):
        ranker = StockOpportunityRanker(
            RankerConfig(top_k=5, min_buy_score=0, min_probability=0)
        )
        signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "601899.SH",
            "symbol_name": "紫金矿业",
            "probability": "68%",
            "prev_day_gain_pct": 0.85,
            "ma20_deviation_pct": 11.3,
            "evidence_list": [
                {
                    "description": "主力资金持续流入",
                    "time": "2026-08-10 19:00:00",
                    "from_source": "individual_fund_flow_agent",
                }
            ],
            "limitations": [],
        }

        scored = ranker.score_signals([signal], "2026-08-10 19:13:31")
        scorecard = scored[0]["next_day_factor_scorecard"]

        self.assertEqual(scorecard["prev_day_gain_pct"], 0.85)
        self.assertEqual(scorecard["ma20_deviation_pct"], 11.3)

    def test_rank_signals_deduplicates_same_symbol(self):
        ranker = StockOpportunityRanker(
            RankerConfig(top_k=5, min_buy_score=0, min_probability=0)
        )
        trigger_time = "2026-08-08 10:00:00"

        signals = [
            {
                "has_opportunity": "yes",
                "action": "buy",
                "symbol_code": "300750.SZ",
                "symbol_name": "宁德时代",
                "probability": "0.72",
                "evidence_list": [
                    {
                        "description": "订单增长，景气改善",
                        "time": "2026-08-08 09:00:00",
                        "from_source": "公司公告",
                    }
                ],
                "limitations": [],
            },
            {
                "has_opportunity": "yes",
                "action": "加仓",
                "symbol_code": "300750.SZ",
                "symbol_name": "宁德时代",
                "probability": "68%",
                "evidence_list": [
                    {
                        "description": "机构上修盈利预测",
                        "time": "2026-08-08 08:30:00",
                        "from_source": "证监会",
                    }
                ],
                "limitations": ["估值较高"],
            },
        ]

        ranked = ranker.rank_signals(signals, trigger_time)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["symbol_code"], "300750.SZ")
        self.assertEqual(ranked[0]["supporting_signal_count"], 2)
        self.assertIn("buy_decision", ranked[0])

    def test_freshness_decay_penalizes_old_evidence(self):
        ranker = StockOpportunityRanker(
            RankerConfig(top_k=5, min_buy_score=0, min_probability=0)
        )
        trigger_time = "2026-08-08 10:00:00"

        recent = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600036.SH",
            "symbol_name": "招商银行",
            "probability": "0.70",
            "evidence_list": [
                {
                    "description": "基本面改善",
                    "time": "2026-08-08 09:50:00",
                    "from_source": "公司公告",
                }
            ],
            "limitations": [],
        }

        old = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "601318.SH",
            "symbol_name": "中国平安",
            "probability": "0.70",
            "evidence_list": [
                {
                    "description": "基本面改善",
                    "time": "2026-08-04 09:50:00",
                    "from_source": "公司公告",
                }
            ],
            "limitations": [],
        }

        scored = ranker.score_signals([recent, old], trigger_time)
        by_code = {x["symbol_code"]: x for x in scored}
        self.assertGreater(by_code["600036.SH"]["buy_score"], by_code["601318.SH"]["buy_score"])

    def test_data_quality_gate_rejects_uncertain_signal(self):
        ranker = StockOpportunityRanker(
            RankerConfig(top_k=5, min_buy_score=40, min_probability=0.5, min_data_quality_score=60)
        )
        trigger_time = "2026-08-08 10:00:00"

        noisy_signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600000.SH",
            "symbol_name": "浦发银行",
            "probability": "75%",
            "evidence_list": [
                {
                    "description": "基于逻辑推断看多",
                    "time": "",
                    "from_source": "逻辑推断",
                }
            ],
            "limitations": ["工具接口异常，代码推断，需再确认"],
            "data_quality_warnings": ["tool_error", "code_uncertain"],
        }

        scored = ranker.score_signals([noisy_signal], trigger_time, system_health={"tool_error_count": 3})
        self.assertEqual(len(scored), 1)
        gate = scored[0]["next_day_gate_report"]
        self.assertFalse(gate["passed"])
        self.assertIn("data_quality", " ".join(gate["failed_reasons"]))

    def test_technical_gate_rejects_bearish_setup(self):
        ranker = StockOpportunityRanker(
            RankerConfig(
                top_k=5,
                min_buy_score=40,
                min_probability=0.5,
                min_data_quality_score=30,
                min_tradeability_score=40,
                min_risk_reward_score=40,
                min_technical_score=65,
                expected_return_floor_pct=-10,
            )
        )
        trigger_time = "2026-08-08 10:00:00"

        bearish_signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600010.SH",
            "symbol_name": "包钢股份",
            "probability": "72%",
            "kline_description": "5/10/20日均线: 9.0 / 9.8 / 10.6",
            "technical_analysis": "均线空头排列，MACD死叉，放量下跌",
            "evidence_list": [
                {
                    "description": "短线冲高回落，趋势转弱",
                    "time": "2026-08-08 09:30:00",
                    "from_source": "公司公告",
                }
            ],
            "limitations": ["短期波动风险"],
        }

        scored = ranker.score_signals([bearish_signal], trigger_time)
        self.assertEqual(len(scored), 1)
        self.assertLess(scored[0]["next_day_factor_scorecard"]["technical_score"], 65)
        gate = scored[0]["next_day_gate_report"]
        self.assertFalse(gate["passed"])
        self.assertIn("technical", " ".join(gate["failed_reasons"]))

    def test_technical_score_rewards_bullish_ma_alignment(self):
        ranker = StockOpportunityRanker(RankerConfig(top_k=5, min_buy_score=0, min_probability=0))
        trigger_time = "2026-08-08 10:00:00"

        bullish_signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600111.SH",
            "symbol_name": "北方稀土",
            "probability": "70%",
            "kline_description": "5/10/20日均线: 12.1 / 11.4 / 10.6",
            "technical_analysis": "均线多头排列，MACD金叉，放量突破",
            "evidence_list": [
                {
                    "description": "站上20日线并突破前高",
                    "time": "2026-08-08 09:35:00",
                    "from_source": "上交所",
                }
            ],
            "limitations": ["注意高位波动"],
        }
        bearish_signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600112.SH",
            "symbol_name": "天成控股",
            "probability": "70%",
            "kline_description": "5/10/20日均线: 10.1 / 10.8 / 11.5",
            "technical_analysis": "均线空头排列，MACD死叉，放量下跌",
            "evidence_list": [
                {
                    "description": "跌破20日线",
                    "time": "2026-08-08 09:35:00",
                    "from_source": "上交所",
                }
            ],
            "limitations": ["注意高位波动"],
        }

        scored = ranker.score_signals([bullish_signal, bearish_signal], trigger_time)
        by_code = {x["symbol_code"]: x for x in scored}
        self.assertGreater(
            by_code["600111.SH"]["next_day_factor_scorecard"]["technical_score"],
            by_code["600112.SH"]["next_day_factor_scorecard"]["technical_score"],
        )
        self.assertGreater(by_code["600111.SH"]["buy_score"], by_code["600112.SH"]["buy_score"])

    def test_multitimeframe_gate_does_not_require_weekly_and_relative_strength_for_short(self):
        """Under T+3~T+5 design, weak weekly/RS does NOT hard-block when the short setup exists."""
        ranker = StockOpportunityRanker(
            RankerConfig(
                top_k=5,
                min_buy_score=0,
                min_probability=0,
                min_tradeability_score=0,
                min_risk_reward_score=0,
                min_data_quality_score=0,
                min_technical_score=0,
                expected_return_floor_pct=-10,
                enforce_multi_timeframe=True,
                min_weekly_trend_score=55,
                min_relative_strength_score=50,
                min_relative_strength_20d_pct=0,
                min_daily_entry_score=50,
            )
        )
        signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600111.SH",
            "symbol_name": "北方稀土",
            "probability": "72%",
            "technical_factor": {
                "weekly_data_available": True,
                "weekly_trend": "bearish",
                "weekly_trend_score": 30,
                "relative_strength_available": True,
                "relative_strength_score": 42,
                "relative_strength_20d_pct": -3.2,
                "relative_strength_60d_pct": -5.0,
                "daily_entry_score": 65,
                "ret_3d_pct": 5.0,
                "ret_5d_pct": 8.0,
                "volume_ratio": 1.4,
                "amount_ratio": 1.5,
            },
            "evidence_list": [
                {
                    "description": "短线放量反弹，但周线趋势转弱且相对大盘走弱",
                    "time": "2026-08-11 09:30:00",
                    "from_source": "公司公告",
                }
            ],
            "limitations": [],
        }

        scored = ranker.score_signals([signal], "2026-08-11 10:00:00")
        gate = scored[0]["next_day_gate_report"]
        failed = " ".join(gate["failed_reasons"])
        self.assertTrue(gate["passed"])
        self.assertNotIn("weekly_trend<", failed)
        self.assertNotIn("relative_strength<", failed)

    def test_multitimeframe_gate_accepts_aligned_weekly_rs_and_daily_setup(self):
        ranker = StockOpportunityRanker(
            RankerConfig(
                top_k=5,
                min_buy_score=0,
                min_probability=0,
                min_tradeability_score=0,
                min_risk_reward_score=0,
                min_data_quality_score=0,
                min_technical_score=0,
                expected_return_floor_pct=-10,
                enforce_multi_timeframe=True,
                min_weekly_trend_score=55,
                min_relative_strength_score=50,
                min_relative_strength_20d_pct=0,
                min_daily_entry_score=50,
            )
        )
        signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600112.SH",
            "symbol_name": "强势标的",
            "probability": "72%",
            "technical_factor": {
                "weekly_data_available": True,
                "weekly_trend": "bullish",
                "weekly_trend_score": 75,
                "relative_strength_available": True,
                "relative_strength_score": 68,
                "relative_strength_20d_pct": 4.2,
                "relative_strength_60d_pct": 8.5,
                "daily_entry_score": 66,
            },
            "evidence_list": [
                {
                    "description": "订单增长，主力资金净流入，站上20日线并放量突破",
                    "time": "2026-08-11 09:30:00",
                    "from_source": "公司公告",
                }
            ],
            "limitations": [],
        }

        ranked = ranker.rank_signals([signal], "2026-08-11 10:00:00")
        self.assertEqual(len(ranked), 1)
        self.assertTrue(ranked[0]["next_day_gate_report"]["passed"])
        scorecard = ranked[0]["next_day_factor_scorecard"]
        self.assertEqual(scorecard["weekly_trend_score"], 75)
        self.assertEqual(scorecard["relative_strength_score"], 68)
        self.assertEqual(scorecard["daily_entry_score"], 66)

    def test_chase_up_gate_blocks_non_primary_catalyst(self):
        ranker = StockOpportunityRanker(
            RankerConfig(
                top_k=5,
                min_buy_score=0,
                min_probability=0,
                min_data_quality_score=0,
                min_tradeability_score=0,
                min_risk_reward_score=0,
                min_technical_score=0,
                expected_return_floor_pct=-10,
                max_prev_day_gain_pct=6.0,
            )
        )
        trigger_time = "2026-08-08 10:00:00"

        signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "002001.SZ",
            "symbol_name": "新和成",
            "probability": "66%",
            "prev_day_gain_pct": 8.2,
            "evidence_list": [
                {
                    "description": "短线情绪活跃，但无新增重大催化",
                    "time": "2026-08-08 09:40:00",
                    "from_source": "上交所",
                }
            ],
            "limitations": ["存在追高风险"],
        }

        scored = ranker.score_signals([signal], trigger_time)
        gate = scored[0]["next_day_gate_report"]
        self.assertFalse(gate["passed"])
        self.assertIn("chase_up", " ".join(gate["failed_reasons"]))

    def test_ma20_deviation_gate_blocks_overextended_price(self):
        ranker = StockOpportunityRanker(
            RankerConfig(
                top_k=5,
                min_buy_score=0,
                min_probability=0,
                min_data_quality_score=0,
                min_tradeability_score=0,
                min_risk_reward_score=0,
                min_technical_score=0,
                expected_return_floor_pct=-10,
                max_ma20_deviation_pct=8.0,
            )
        )
        trigger_time = "2026-08-08 10:00:00"

        signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "002002.SZ",
            "symbol_name": "鸿达兴业",
            "probability": "67%",
            "kline_description": "收盘: 12.6 开盘: 12.0 最高: 12.8 最低: 11.9 5/10/20日均线: 11.9 / 11.2 / 10.8",
            "evidence_list": [
                {
                    "description": "短线走强",
                    "time": "2026-08-08 09:35:00",
                    "from_source": "上交所",
                }
            ],
            "limitations": ["注意冲高回落"],
        }

        scored = ranker.score_signals([signal], trigger_time)
        gate = scored[0]["next_day_gate_report"]
        self.assertFalse(gate["passed"])
        self.assertIn("ma20_deviation", " ".join(gate["failed_reasons"]))

    def test_ma20_negative_distance_blocks_bearish_candidate(self):
        ranker = StockOpportunityRanker(
            RankerConfig(
                top_k=5,
                min_buy_score=0,
                min_probability=0,
                min_data_quality_score=0,
                min_tradeability_score=0,
                min_risk_reward_score=0,
                min_technical_score=45,
                expected_return_floor_pct=-10,
                max_ma20_deviation_pct=8.0,
            )
        )
        trigger_time = "2026-08-10 11:20:16"

        signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "300502.SZ",
            "symbol_name": "新易盛",
            "probability": "68%",
            "ma20_deviation_pct": -10.5,
            "evidence_list": [
                {
                    "description": "机构资金净买入，AI光模块热度较高",
                    "time": "2026-08-10 09:30:00",
                    "from_source": "机构",
                }
            ],
            "limitations": [],
        }

        scored = ranker.score_signals([signal], trigger_time)
        scorecard = scored[0]["next_day_factor_scorecard"]
        gate = scored[0]["next_day_gate_report"]
        failed = " ".join(gate["failed_reasons"])
        self.assertLess(scorecard["technical_score"], 45)
        self.assertFalse(gate["passed"])
        self.assertIn("technical", failed)
        self.assertIn("ma20_deviation", failed)

        watchlist = ranker.build_watchlist([signal], trigger_time, top_k=5)
        self.assertEqual(watchlist, [])

    def test_flow_confirmation_gate_blocks_weak_flow_when_data_available(self):
        ranker = StockOpportunityRanker(
            RankerConfig(
                top_k=5,
                min_buy_score=0,
                min_probability=0,
                min_data_quality_score=0,
                min_tradeability_score=0,
                min_risk_reward_score=0,
                min_technical_score=0,
                expected_return_floor_pct=-10,
                min_flow_confirmation_score=70,
                min_regime_confirmation_score=70,
                enforce_flow_confirmation_if_available=True,
            )
        )
        trigger_time = "2026-08-08 10:00:00"

        signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "002003.SZ",
            "symbol_name": "伟星股份",
            "probability": "70%",
            "evidence_list": [
                {
                    "description": "情绪一般，未见资金净买入",
                    "time": "2026-08-08 09:30:00",
                    "from_source": "财经网站",
                }
            ],
            "limitations": ["资金承接尚弱"],
        }

        scored = ranker.score_signals(
            [signal],
            trigger_time,
            market_context={"market_trend": "neutral", "risk_sentiment": "neutral", "has_sector_flow_data": True},
        )
        gate = scored[0]["next_day_gate_report"]
        self.assertFalse(gate["passed"])
        self.assertIn("flow", " ".join(gate["failed_reasons"]))
        self.assertIn("regime", " ".join(gate["failed_reasons"]))

    def test_flow_confirmation_uses_concrete_amount_evidence(self):
        """Top-tier evidence with real net-inflow magnitude should pass flow gate."""
        ranker = StockOpportunityRanker(
            RankerConfig(
                min_buy_score=0,
                min_probability=0,
                min_data_quality_score=0,
                min_tradeability_score=0,
                min_risk_reward_score=0,
                min_technical_score=0,
                expected_return_floor_pct=-10,
                min_flow_confirmation_score=55,
                min_regime_confirmation_score=50,
                enforce_flow_confirmation_if_available=True,
            )
        )
        signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "000636.SZ",
            "symbol_name": "风华高科",
            "probability": "0.62",
            "evidence_list": [
                {
                    "description": "风华高科当日主力净流入10.5亿元，MLCC方向板块主力净流入28.38亿元居首。",
                    "time": "2026-08-03 18:00:00",
                    "from_source": "sector_fund_flow_trend_agent",
                },
                {
                    "description": "技术面日线评分82分，量比1.60，属于可关注启动初期。",
                    "time": "2026-08-03 18:00:00",
                    "from_source": "technical_indicators_agent",
                },
            ],
            "limitations": [],
        }
        scored = ranker.score_signals(
            [signal],
            "2026-08-03 18:00:00",
            market_context={"has_sector_flow_data": True, "market_trend": "neutral", "risk_sentiment": "risk_on"},
        )[0]
        gate = scored["next_day_gate_report"]
        flow = scored["next_day_factor_scorecard"]["capital_flow_score"]
        self.assertGreaterEqual(flow, 55)
        self.assertNotIn("flow<", " ".join(gate["failed_reasons"]))



class TestFinancialEvidenceConsistency(unittest.TestCase):
    def test_financial_claim_caveat_blocks_buy(self):
        ranker = StockOpportunityRanker(RankerConfig())
        signal = {
            "has_opportunity": "是",
            "action": "买入",
            "symbol_code": "000703.SZ",
            "symbol_name": "恒逸石化",
            "probability": "62%",
            "evidence_list": [
                {
                    "description": "上半年归母净利润59.02亿元，同比暴增2500.73%，推出首次中期分红。",
                    "time": "2026-08-12 18:00:00",
                    "from_source": "global_summary",
                }
            ],
            "limitations": [
                "材料来源与公司公告存在口径差异，需以正式财报为准。"
            ],
        }
        scored = ranker.score_signals(
            [signal],
            "2026-08-12 18:00:00",
            market_context={"has_sector_flow_data": True},
            system_health={},
        )[0]
        self.assertFalse(scored["next_day_gate_report"]["passed"])
        self.assertIn("financial_evidence_caveat", scored["next_day_gate_report"]["failed_reasons"])
        self.assertIn("financial_statement_conflict", scored["next_day_gate_report"]["failed_reasons"])

    def test_financial_negative_figure_in_limitations_blocks_buy(self):
        ranker = StockOpportunityRanker(RankerConfig())
        signal = {
            "has_opportunity": "是",
            "action": "买入",
            "symbol_code": "000703.SZ",
            "symbol_name": "恒逸石化",
            "probability": "62%",
            "evidence_list": [
                {
                    "description": "净利润同比大增2502.73%，业绩拐点确立。",
                    "time": "2026-08-12 18:00:00",
                    "from_source": "sina_summary_agent",
                }
            ],
            "limitations": [
                "公司公告净利润同比下滑47.32%，与媒体口径存在较大差异。"
            ],
        }
        scored = ranker.score_signals(
            [signal],
            "2026-08-12 18:00:00",
            market_context={"has_sector_flow_data": True},
            system_health={},
        )[0]
        self.assertFalse(scored["next_day_gate_report"]["passed"])
        self.assertIn("financial_claim_conflict", scored["next_day_gate_report"]["failed_reasons"])


class TestShortCatalystAndRrGate(unittest.TestCase):
    def _ranker(self):
        return StockOpportunityRanker(
            RankerConfig(
                min_buy_score=0,
                min_probability=0,
                min_tradeability_score=0,
                min_risk_reward_score=0,
                min_data_quality_score=0,
                min_technical_score=0,
                expected_return_floor_pct=-10,
                enforce_flow_confirmation_if_available=False,
                reject_below_rr_without_company_catalyst=True,
                min_rr_without_company_catalyst=1.0,
            )
        )

    def _signal(self, event_type="sector_flow", rr=0.6, with_company_catalyst_text=False):
        ev = [
            {
                "description": "板块资金净流入，个股跟涨"
                + ("，公司公告新增订单超预期" if with_company_catalyst_text else ""),
                "time": "2026-08-17 09:30:00",
                "from_source": "公司公告" if with_company_catalyst_text else "sector_fund_flow_trend_agent",
            }
        ]
        plan = {"plan": {"rr_1": rr}, "status": "ok"}
        return {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600001.SH",
            "symbol_name": "测试标的",
            "probability": "70%",
            "event_type": event_type,
            "evidence_list": ev,
            "limitations": [],
            "trade_plan": plan,
        }

    def test_sector_only_and_rr_below_one_is_rejected(self):
        scored = self._ranker().score_signals(
            [self._signal(event_type="sector_flow", rr=0.6, with_company_catalyst_text=False)],
            "2026-08-18 10:00:00",
        )[0]
        gate = scored["next_day_gate_report"]
        self.assertFalse(gate["passed"])
        self.assertIn("rr<1.0_no_company_catalyst", " ".join(gate["failed_reasons"]))

    def test_company_catalyst_and_rr_below_one_is_not_hard_rejected_by_new_gate(self):
        scored = self._ranker().score_signals(
            [self._signal(event_type="order_win", rr=0.6, with_company_catalyst_text=True)],
            "2026-08-18 10:00:00",
        )[0]
        gate = scored["next_day_gate_report"]
        failed = " ".join(gate["failed_reasons"])
        self.assertNotIn("rr<1.0_no_company_catalyst", failed)

    def test_company_catalyst_and_rr_ok_passes(self):
        scored = self._ranker().score_signals(
            [self._signal(event_type="order_win", rr=1.5, with_company_catalyst_text=True)],
            "2026-08-18 10:00:00",
        )[0]
        self.assertTrue(scored["next_day_gate_report"]["passed"])



class TestSectorOutflowGate(unittest.TestCase):
    def setUp(self):
        self.ranker = StockOpportunityRanker(
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
        self.signal = {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600602.SH",
            "symbol_name": "测试半导体",
            "probability": "70%",
            "event_type": "sector_flow",
            "evidence_list": [
                {
                    "description": "半导体板块今日主力净流出152.6亿元，个股当日涨停",
                    "time": "2026-08-18 09:40:00",
                    "from_source": "sector_fund_flow_trend_agent",
                }
            ],
            "limitations": ["板块资金面偏弱"],
        }

    def test_sector_only_and_block_outflow_is_rejected(self):
        scored = self.ranker.score_signals([self.signal], "2026-08-18 10:00:00")[0]
        gate = scored["next_day_gate_report"]
        self.assertFalse(gate["passed"])
        self.assertIn("sector_main_net_outflow", " ".join(gate["failed_reasons"]))

    def test_sector_outflow_block_with_company_catalyst_does_not_break(self):
        signal = dict(self.signal)
        signal["event_type"] = "price_hike"
        signal["evidence_list"] = [
            {
                "description": "公司产品涨价20%，同时半导体板块主力净流出50亿",
                "time": self.signal["evidence_list"][0]["time"],
                "from_source": "公司公告",
            }
        ]
        scored = self.ranker.score_signals([signal], "2026-08-18 10:00:00")[0]
        gate = scored["next_day_gate_report"]
        # outflow <100 and company catalyst => not rejected by this gate
        failed = " ".join(gate["failed_reasons"])
        self.assertNotIn("sector_main_net_outflow", failed)



class TestSetupMetaOutput(unittest.TestCase):
    def setUp(self):
        self.ranker = StockOpportunityRanker(
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

    def _signal(self, event_type="sector_flow", company_catalyst=False):
        desc = "板块资金净流入，个股跟涨"
        if company_catalyst:
            desc += "，公司公告新增订单超预期"
        return {
            "has_opportunity": "yes",
            "action": "buy",
            "symbol_code": "600700.SH",
            "symbol_name": "状态测试",
            "probability": "70%",
            "event_type": event_type,
            "technical_factor": {
                "ma20_deviation_pct": 3.0,
                "rsi": 55,
                "relative_strength_20d_pct": 1.2,
                "breakout_20d": True,
                "short_setup_score": 90,
            },
            "evidence_list": [
                {
                    "description": desc,
                    "time": "2026-08-17 09:30:00",
                    "from_source": "公司公告" if company_catalyst else "sector_fund_flow_trend_agent",
                }
            ],
            "limitations": [],
        }

    def test_sector_follow_outputs_d_state(self):
        scored = self.ranker.score_signals([self._signal()], "2026-08-18 10:00:00")[0]
        meta = scored.get("setup_meta") or {}
        self.assertEqual(meta.get("risk_state"), "D_纯板块跟随")
        self.assertEqual(meta.get("driver_quality"), "sector_follow")
        self.assertEqual(scored.get("signal_confidence_type"), "subjective_confidence_not_backtest")
        self.assertEqual(scored.get("expected_return_method"), "heuristic_edge_from_scoring_formula")

    def test_company_catalyst_outputs_company_driven(self):
        scored = self.ranker.score_signals(
            [self._signal(event_type="order_win", company_catalyst=True)],
            "2026-08-18 10:00:00",
        )[0]
        meta = scored.get("setup_meta") or {}
        self.assertEqual(meta.get("risk_state"), "B_公司催化启动")
        self.assertEqual(meta.get("driver_quality"), "company")


if __name__ == "__main__":
    unittest.main()

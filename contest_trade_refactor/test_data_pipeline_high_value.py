import unittest

import pandas as pd

from agents.data_analysis_pipeline import DataAnalysisPipeline


class TestDataPipelineHighValueSelection(unittest.TestCase):
    def test_high_value_news_selection_prefers_relevant_docs(self):
        pipeline = DataAnalysisPipeline(
            agent_name="test_high_value",
            source_list=[],
            high_value_keep_ratio=0.4,
            high_value_min_docs=2,
            high_value_max_docs=3,
        )

        df = pd.DataFrame(
            [
                {
                    "title": "央行宣布降准 影响银行与地产",
                    "content": "政策落地时间表明确，并给出资金规模与行业传导路径。",
                    "pub_time": "2026-08-08 09:30:00",
                    "market_relevance_score": 6,
                    "market_relevance_label": "relevant",
                    "signal_event_type": "monetary_policy",
                    "signal_direction": "bullish",
                    "signal_confidence": 0.8,
                },
                {
                    "title": "某公司发布回购计划",
                    "content": "回购金额上限提升，净利润同比增长。",
                    "pub_time": "2026-08-08 09:00:00",
                    "market_relevance_score": 4,
                    "market_relevance_label": "relevant",
                    "signal_event_type": "corporate_action",
                    "signal_direction": "bullish",
                    "signal_confidence": 0.65,
                },
                {
                    "title": "娱乐综艺节目播出",
                    "content": "娱乐信息为主，与资本市场关系弱。",
                    "pub_time": "2026-08-08 08:50:00",
                    "market_relevance_score": 0,
                    "market_relevance_label": "noise",
                    "signal_event_type": "other",
                    "signal_direction": "neutral",
                    "signal_confidence": 0.1,
                },
                {
                    "title": "监管部门发布新规",
                    "content": "对券商资本约束与风险准备金做出调整。",
                    "pub_time": "2026-08-08 09:10:00",
                    "market_relevance_score": 5,
                    "market_relevance_label": "relevant",
                    "signal_event_type": "regulation",
                    "signal_direction": "bearish",
                    "signal_confidence": 0.72,
                },
            ]
        )

        selected = pipeline._select_high_value_news(df)
        self.assertEqual(len(selected), 2)
        selected_titles = set(selected["title"].tolist())
        self.assertIn("央行宣布降准 影响银行与地产", selected_titles)
        self.assertIn("监管部门发布新规", selected_titles)
        self.assertNotIn("娱乐综艺节目播出", selected_titles)

    def test_normalize_source_dataframe_adds_optional_columns(self):
        pipeline = DataAnalysisPipeline(agent_name="test_norm", source_list=[])
        raw_df = pd.DataFrame(
            [
                {"title": "标题A", "content": "内容A", "pub_time": "2026-08-08 09:00:00"},
                {"title": "", "content": "内容B", "pub_time": "2026-08-08 09:01:00"},
            ]
        )

        normalized = pipeline._normalize_source_dataframe(raw_df)
        self.assertEqual(len(normalized), 1)
        self.assertIn("market_relevance_score", normalized.columns)
        self.assertIn("signal_event_type", normalized.columns)


if __name__ == "__main__":
    unittest.main()


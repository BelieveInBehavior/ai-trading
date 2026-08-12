import unittest

from utils.system_health_utils import (
    count_data_factor_tool_errors,
    count_research_tool_call_errors,
    count_tool_failure_mentions_in_text,
    factor_content_is_usable,
    summarize_research_agent_tool_errors,
    text_indicates_tool_failure,
)


class TestSystemHealthUtils(unittest.TestCase):
    def test_factor_content_is_usable(self):
        self.assertTrue(factor_content_is_usable("## 20260810 融资融券异动分析"))
        self.assertFalse(factor_content_is_usable("融资融券数据获取失败"))

    def test_count_data_factor_tool_errors(self):
        factors = [
            {"context_string": "正常融资融券报告"},
            {"context_string": "大宗交易数据获取失败"},
        ]
        self.assertEqual(count_data_factor_tool_errors(factors), 1)

    def test_count_research_tool_call_errors(self):
        tool_calls = [
            {"result": {"success": True, "data": "ok"}},
            {"result": {"success": False, "error_message": "执行超时（120.0秒）"}},
        ]
        self.assertEqual(count_research_tool_call_errors(tool_calls), 1)

    def test_text_indicates_tool_failure_ignores_benign_phrases(self):
        benign = "\n".join([
            "建设机械已经停牌，无法交易",
            "若次日板块情绪未能回暖，可能延续弱势",
            "无法确认海外资金对封测板块的态度",
        ])
        self.assertFalse(text_indicates_tool_failure(benign))

    def test_text_indicates_tool_failure_detects_real_issues(self):
        real = "company_financial_info：查询江波龙财务数据超时\nstock_summary failed"
        self.assertTrue(text_indicates_tool_failure(real))
        self.assertEqual(count_tool_failure_mentions_in_text(real), 2)

    def test_summarize_research_agent_prefers_tool_calls(self):
        class Result:
            final_result_thinking = "stock_summary failed"

        tool_calls = [{"result": {"success": False, "error_message": "执行超时（120.0秒）"}}]
        self.assertEqual(summarize_research_agent_tool_errors(Result(), tool_calls), 1)

    def test_summarize_research_agent_falls_back_to_thinking_when_cached(self):
        class Result:
            final_result_thinking = "company_financial_info：查询江波龙财务数据超时"

        self.assertEqual(summarize_research_agent_tool_errors(Result(), []), 1)


if __name__ == "__main__":
    unittest.main()

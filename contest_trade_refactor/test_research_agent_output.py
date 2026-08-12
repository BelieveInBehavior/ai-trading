import unittest
from types import SimpleNamespace
from unittest.mock import patch

import agents.research_agent_loop as research_agent_module
from agents.research_agent_loop import ResearchAgentLoop


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    async def a_run(self, *args, **kwargs):
        return self.responses.pop(0)


class TestResearchAgentOutput(unittest.IsolatedAsyncioTestCase):
    async def test_empty_thinking_response_retries_visible_final_output(self):
        agent = object.__new__(ResearchAgentLoop)
        agent.trigger_time = "2026-08-11 10:00:00"
        agent.task = "Find next-day buy opportunities."
        agent.background_information = "market data"
        agent.plan_result = "research plan"
        agent.tool_calls = []
        agent.config = SimpleNamespace(output_language="中文")
        agent.tool_manager = SimpleNamespace(
            build_toolcall_context=lambda: "[]"
        )

        fallback_json = '{"signals": []}'
        with patch.dict(
            research_agent_module.cfg.llm_thinking,
            {"api_key": "test-thinking-key"},
            clear=False,
        ):
            with patch.object(
                research_agent_module,
                "GLOBAL_THINKING_LLM",
                _FakeLLM([
                    SimpleNamespace(
                        content="",
                        reasoning_content="The hidden reasoning was generated.",
                    )
                ]),
            ):
                with patch.object(
                    research_agent_module,
                    "GLOBAL_LLM",
                    _FakeLLM([
                        SimpleNamespace(content=fallback_json, reasoning_content=""),
                    ]),
                ):
                    final_result, reasoning = await agent._write_final_report()

        self.assertEqual(final_result, fallback_json)
        self.assertIn("hidden reasoning", reasoning)


if __name__ == "__main__":
    unittest.main()

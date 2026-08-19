"""
Research Agent Loop Implementation

Refactored from LangGraph to explicit loop control.
Implements ReAct pattern: Plan → [Tool Selection → Tool Execution]* → Write Result
"""

import json
import textwrap
from typing import Dict, Any, List
from pathlib import Path
from dataclasses import dataclass

from agents.base_agent_loop import ReactAgentLoop, AgentLoopConfig
from agents.prompts import (
    prompt_for_research_plan,
    prompt_for_research_choose_tool,
    prompt_for_research_write_result,
    prompt_for_research_invest_task,
    prompt_for_research_invest_output_format,
)
from models.llm_model import GLOBAL_LLM, GLOBAL_THINKING_LLM
from tools.tool_utils import ToolManager, ToolManagerConfig
from config.config import cfg, WORKSPACE_ROOT
from utils.llm_utils import count_tokens
from utils.market_manager import GLOBAL_MARKET_MANAGER
from utils.report_utils import generate_research_agent_report
from loguru import logger


@dataclass
class ResearchAgentInput:
    """Research Agent Input"""
    trigger_time: str
    background_information: str


@dataclass
class ResearchAgentOutput:
    """Research Agent Output"""
    task: str
    trigger_time: str
    background_information: str
    belief: str
    final_result: str
    final_result_thinking: str

    def to_dict(self):
        return {
            "task": self.task,
            "trigger_time": self.trigger_time,
            "background_information": self.background_information,
            "belief": self.belief,
            "final_result": self.final_result,
            "final_result_thinking": self.final_result_thinking,
        }


@dataclass
class ResearchAgentLoopConfig(AgentLoopConfig):
    """Research Agent specific configuration"""
    belief: str = ""
    plan_enabled: bool = True
    react_enabled: bool = True
    output_language: str = "中文"
    tool_config: ToolManagerConfig = None

    def __init__(
        self,
        agent_name: str = "research_agent",
        belief: str = "",
        tools_paths: List[str] | None = None,
        **kwargs
    ):
        # Initialize base config
        super().__init__(agent_name=agent_name, **kwargs)

        # Research agent specific
        self.belief = belief
        self.max_iterations = cfg.research_agent_config.get("max_react_step", 10)
        tool_paths = tools_paths or cfg.research_agent_config.get("tools") or []
        self.tool_config = ToolManagerConfig(list(tool_paths))
        self.output_language = cfg.system_language
        self.plan_enabled = cfg.research_agent_config.get("plan", True)
        self.react_enabled = cfg.research_agent_config.get("react", True)

        # Setup workspace
        self.workspace_dir = WORKSPACE_ROOT / "reports" / agent_name


class ResearchAgentLoop(ReactAgentLoop):
    """
    Research Agent using explicit loop control.

    Flow:
    1. Initialize: Load cache or setup state
    2. Plan: Create research plan (optional)
    3. Loop:
       - Select tool (LLM-based)
       - Execute tool
       - Record result
    4. Finalize: Write final report
    """

    def __init__(self, config: ResearchAgentLoopConfig):
        super().__init__(config)
        self.config: ResearchAgentLoopConfig = config
        self.tool_manager = ToolManager(self.config.tool_config)

        # Research agent state
        self.trigger_time = ""
        self.task = ""
        self.background_information = ""
        self.plan_result = ""

    async def initialize(self, input_data: ResearchAgentInput):
        """Initialize research agent state"""
        self.trigger_time = input_data.trigger_time
        self.background_information = input_data.background_information
        self.task = self.get_invest_prompt()

        # Try to load cached result
        cached_result = self._load_cached_result()
        if cached_result:
            self.result = cached_result
            if self.config.verbose:
                print(f"[{self.config.agent_name}] Loaded cached result for {self.trigger_time}")
            return

        # Create research plan if enabled
        if self.config.plan_enabled:
            self.plan_result = await self._create_plan()
            if self.config.verbose:
                print(f"[{self.config.agent_name}] Plan created:\n{self.plan_result[:200]}...")
        else:
            self.plan_result = ""

    async def _create_plan(self) -> str:
        """Create research plan"""
        try:
            prompt = prompt_for_research_plan.format(
                current_time=self.trigger_time,
                task=self.task,
                background_information=self.background_information,
                tools_info=self.tool_manager.build_toolcall_context(),
                output_language=self.config.output_language,
            )
            messages = [{"role": "user", "content": prompt}]
            response = await GLOBAL_LLM.a_run(
                messages, verbose=False, thinking=False, max_retries=10
            )
            return response.content.strip()
        except Exception as e:
            logger.error(f"Error creating plan: {e}")
            return ""

    async def select_tool(self) -> Dict[str, Any]:
        """Select next tool using LLM"""
        # If ReAct disabled or max iterations reached, use final_report
        if not self.config.react_enabled or self.iteration >= self.config.max_iterations:
            return {"tool_name": "final_report"}

        # Build prompt with tool call history
        tool_call_context = self.get_tool_call_context()

        prompt = prompt_for_research_choose_tool.format(
            current_time=self.trigger_time,
            task=self.task,
            plan=self.plan_result,
            background_information=self.background_information,
            tool_call_context=tool_call_context,
            tools_info=self.tool_manager.build_toolcall_context(),
            output_language=self.config.output_language,
        )

        try:
            selected_tool = await self.tool_manager.select_tool_by_llm(prompt=prompt)
            if self.config.verbose:
                print(f"[{self.config.agent_name}] Selected tool: {selected_tool.get('tool_name', 'unknown')}")
            return selected_tool
        except Exception as e:
            logger.error(f"Error selecting tool: {e}")
            return {"error": str(e), "error_msg": "Tool selection failed"}

    async def execute_tool(self, tool: Dict[str, Any]) -> Any:
        """Execute selected tool"""
        try:
            # Handle tool selection errors
            if "error" in tool:
                logger.warning(f"Tool selection error: {tool.get('error_msg', 'Unknown error')}")
                return tool

            tool_name = tool["tool_name"]
            tool_args = tool.get("properties", {})

            if self.config.verbose:
                print(f"[{self.config.agent_name}] Executing tool: {tool_name}")

            result = await self.tool_manager.call_tool(
                tool_name, tool_args, self.trigger_time
            )

            if self.config.verbose:
                result_preview = str(result)[:200] if result else "None"
                print(f"[{self.config.agent_name}] Tool result: {result_preview}...")

            return result

        except Exception as e:
            logger.error(f"Error executing tool {tool.get('tool_name', 'unknown')}: {e}")
            return {"error": str(e)}

    def should_terminate(self) -> bool:
        """Check if loop should terminate"""
        # Check basic conditions (cached result, max iterations, manual termination)
        if self._check_basic_termination():
            return True

        # Check if context is too long (approaching token limit)
        if self._is_context_too_long():
            if self.config.verbose:
                print(f"[{self.config.agent_name}] Context too long, terminating")
            return True

        # Check if last step was finalize
        if self.context.steps and self.context.steps[-1].get("step_type") == "finalize":
            return True

        return False

    def _is_context_too_long(self) -> bool:
        """Check if context exceeds token limit"""
        try:
            # Estimate context size
            estimated_prompt = prompt_for_research_write_result.format(
                current_time=self.trigger_time,
                task=self.task,
                background_information=self.background_information,
                plan=self.plan_result,
                tool_call_context=self.get_tool_call_context(),
                tools_info=self.tool_manager.build_toolcall_context(),
                output_format=self.get_output_format(),
                output_language=self.config.output_language,
            )
            token_count = count_tokens(estimated_prompt)
            return token_count > self.config.max_context_tokens
        except Exception as e:
            logger.error(f"Error checking context length: {e}")
            return False

    async def finalize(self) -> ResearchAgentOutput:
        """Generate final research report"""
        # If cached result exists, return it
        if self.result is not None:
            return self.result

        # Generate final report
        if self.config.verbose:
            print(f"[{self.config.agent_name}] Generating final report...")

        try:
            final_result, final_thinking = await self._write_final_report()

            # Create output object
            output = ResearchAgentOutput(
                task=self.task,
                trigger_time=self.trigger_time,
                background_information=self.background_information,
                belief=self.config.belief,
                final_result=final_result,
                final_result_thinking=final_thinking,
            )

            # Save to cache
            self._save_cached_result(output)

            # Generate markdown report
            self._generate_report(output)

            return output

        except Exception as e:
            logger.error(f"Error finalizing: {e}")
            import traceback
            traceback.print_exc()
            # Return empty result
            return ResearchAgentOutput(
                task=self.task,
                trigger_time=self.trigger_time,
                background_information=self.background_information,
                belief=self.config.belief,
                final_result="",
                final_result_thinking="",
            )

    async def _write_final_report(self) -> tuple[str, str]:
        """Write final report using LLM"""
        prompt = prompt_for_research_write_result.format(
            current_time=self.trigger_time,
            task=self.task,
            background_information=self.background_information,
            plan=self.plan_result,
            tool_call_context=self.get_tool_call_context(),
            tools_info=self.tool_manager.build_toolcall_context(),
            output_format=self.get_output_format(),
            output_language=self.config.output_language,
        )

        messages = [{"role": "user", "content": prompt}]

        reasoning_content = ""
        final_content = ""
        try:
            # Some thinking providers put the whole answer in the hidden
            # reasoning channel. Keep a visible-output fallback below.
            if cfg.llm_thinking.get("api_key"):
                response = await GLOBAL_THINKING_LLM.a_run(
                    messages, verbose=False, thinking=True, max_retries=5
                )
            else:
                response = await GLOBAL_LLM.a_run(
                    messages, verbose=False, thinking=False, max_retries=5
                )
            final_content = str(getattr(response, "content", "") or "").strip()
            reasoning_content = str(
                getattr(response, "reasoning_content", "") or ""
            ).strip()
        except Exception as exc:
            logger.warning(f"Primary final report generation failed: {exc}")

        if final_content:
            return final_content, reasoning_content

        fallback_prompt = (
            f"{prompt}\n\n"
            "CRITICAL OUTPUT REQUIREMENT:\n"
            "Return the visible final answer now. Do not put the answer only in "
            "hidden reasoning. The visible response must contain the requested "
            "JSON signal object, even when the correct result is an empty "
            "signals list.\n"
        )
        try:
            fallback_response = await GLOBAL_LLM.a_run(
                [{"role": "user", "content": fallback_prompt}],
                verbose=False,
                thinking=False,
                max_retries=3,
            )
            fallback_content = str(
                getattr(fallback_response, "content", "") or ""
            ).strip()
            if fallback_content:
                return fallback_content, reasoning_content
        except Exception as exc:
            logger.warning(f"Fallback final report generation failed: {exc}")

        return "", reasoning_content

    def _load_cached_result(self) -> ResearchAgentOutput:
        """Load cached result from file"""
        if not self.config.enable_cache:
            return None

        filename = f'{self.trigger_time.replace(" ", "_").replace(":", "-")}.json'
        data = self.load_from_file(filename)

        if data:
            try:
                return ResearchAgentOutput(**data)
            except Exception as e:
                logger.error(f"Error loading cached result: {e}")
                return None

        return None

    def _save_cached_result(self, output: ResearchAgentOutput):
        """Save result to cache file"""
        if not self.config.enable_cache:
            return

        filename = f'{self.trigger_time.replace(" ", "_").replace(":", "-")}.json'
        self.save_to_file(output.to_dict(), filename)

    def _generate_report(self, output: ResearchAgentOutput):
        """Generate markdown report"""
        try:
            report_path = generate_research_agent_report(
                output.to_dict(), self.config.agent_name
            )
            if report_path and self.config.verbose:
                print(f"[{self.config.agent_name}] Report generated: {report_path}")
        except Exception as e:
            logger.error(f"Error generating report: {e}")

    # Helper methods for building prompts
    def build_background_information(
        self, trigger_time: str, belief: str, factors: List, research_scope: str = ""
    ) -> str:
        """Build background information from data factors.

        ``research_scope`` is an optional mandatory candidate list that the agent
        must start from; it appears prominently in the prompt so the research
        step cannot silently ignore the quantitative candidate pool.
        """
        global_market_information = ""

        for factor in factors:
            # Handle different factor types
            if hasattr(factor, "result") and factor.result:
                factor_output = factor.result
                factor_name = factor_output.agent_name
                factor_update_time = factor_output.trigger_time
                factor_context = factor_output.context_string
            elif hasattr(factor, "agent_name"):
                factor_name = factor.agent_name
                factor_update_time = factor.trigger_time
                factor_context = factor.context_string
            elif isinstance(factor, dict):
                factor_name = factor.get("agent_name", "unknown")
                factor_update_time = factor.get("trigger_time", trigger_time)
                factor_context = factor.get("context_string", "")
            else:
                continue

            global_market_information += textwrap.dedent(
                f"""
            <global_summary>
            <source>{factor_name}</source>
            <timestamp>{factor_update_time}</timestamp>
            <content>{factor_context}</content>
            </global_summary>
            """
            )

        target_market = GLOBAL_MARKET_MANAGER.get_target_symbol_context(trigger_time)

        background_information_format = textwrap.dedent(
            """
        <market_information>
        {global_market_information}
        </market_information>

        <target_market>
        {target_market}
        </target_market>

        <your_belief>
        {belief}
        </your_belief>

        <research_scope>
        {research_scope}
        </research_scope>
        """
        )

        return background_information_format.format(
            global_market_information=global_market_information,
            target_market=target_market,
            belief=belief,
            research_scope=research_scope,
        )

    def get_invest_prompt(self) -> str:
        """Get investment task prompt"""
        return prompt_for_research_invest_task

    def get_output_format(self) -> str:
        """Get output format specification"""
        return prompt_for_research_invest_output_format


# For backward compatibility
ResearchAgent = ResearchAgentLoop
ResearchAgentConfig = ResearchAgentLoopConfig


if __name__ == "__main__":
    import asyncio

    async def test():
        config = ResearchAgentLoopConfig(
            agent_name="test_research_agent",
            belief="Test belief",
            max_iterations=5,
        )

        agent = ResearchAgentLoop(config)

        input_data = ResearchAgentInput(
            trigger_time="2025-07-09 09:00:00",
            background_information="Test background information",
        )

        result = await agent.run(input_data)
        print(f"Result: {result.to_dict()}")

    asyncio.run(test())

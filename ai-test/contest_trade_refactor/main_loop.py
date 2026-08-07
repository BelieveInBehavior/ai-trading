"""
Simplified Trade Company - Agent Loop Version

Refactored from LangGraph to direct async orchestration.
Uses the new agent loop implementations for cleaner control flow.
"""

import re
import json
import asyncio
from datetime import datetime
from typing import List, Dict
from pathlib import Path

from config.config import cfg, PROJECT_ROOT
from agents.data_analysis_pipeline import DataAnalysisPipeline
from agents.research_agent_loop import (
    ResearchAgentLoop,
    ResearchAgentLoopConfig,
    ResearchAgentInput,
)
from utils.market_manager import GLOBAL_MARKET_MANAGER


class SimpleTradeCompany:
    """
    Simplified Trade Company using proper architecture patterns.

    Architecture:
    - Data Analysis: Pipeline pattern (fixed steps, linear flow)
    - Research: Agent Loop pattern (dynamic decisions, ReAct loop)
    - Orchestration: Simple async coordination
    """

    def __init__(self):
        self.workspace_dir = PROJECT_ROOT / "agents_workspace"

        # Initialize Data Agents (using Pipeline)
        self.data_agents = {}
        for agent_idx, agent_config in enumerate(cfg.data_agents_config):
            self.data_agents[agent_idx] = DataAnalysisPipeline(
                agent_name=agent_config["agent_name"],
                source_list=agent_config["data_source_list"],
                final_target_tokens=agent_config.get("final_target_tokens", 4000),
                bias_goal=agent_config.get("bias_goal", ""),
            )

        # Initialize Research Agents
        self.research_agents = {}
        belief_list_path = PROJECT_ROOT / cfg.research_agent_config["belief_list_path"]

        with open(belief_list_path, 'r', encoding='utf-8') as f:
            belief_list = json.load(f)

        for agent_idx, belief in enumerate(belief_list):
            config = ResearchAgentLoopConfig(
                agent_name=f"agent_{agent_idx}",
                belief=belief,
                verbose=True,
            )
            self.research_agents[agent_idx] = ResearchAgentLoop(config)

    async def run(self, trigger_time: str) -> Dict:
        """
        Run the entire trading company workflow.

        Args:
            trigger_time: Trigger time for analysis

        Returns:
            Dictionary with data_factors, research_signals, and best_signals
        """
        print(f"🚀 Starting Trade Company Analysis at {trigger_time}")
        print("=" * 80)

        # Stage 1: Run Data Agents in parallel
        print("\n📊 Stage 1: Running Data Agents...")
        data_factors = await self._run_data_agents(trigger_time)
        print(f"✅ Data Agents completed: {len(data_factors)} factors generated")

        # Stage 2: Run Research Agents in parallel
        print("\n🔍 Stage 2: Running Research Agents...")
        research_signals = await self._run_research_agents(trigger_time, data_factors)
        print(f"✅ Research Agents completed: {len(research_signals)} signals generated")

        # Stage 3: Select best signals
        print("\n🎯 Stage 3: Selecting best signals...")
        best_signals = self._select_best_signals(research_signals)
        print(f"✅ Selected {len(best_signals)} best signals")

        print("\n" + "=" * 80)
        print("✅ Trade Company Analysis Completed")

        return {
            "trigger_time": trigger_time,
            "data_factors": data_factors,
            "research_signals": research_signals,
            "best_signals": best_signals,
        }

    async def _run_data_agents(self, trigger_time: str) -> List:
        """Run all data agents (pipelines) in parallel"""
        tasks = []

        for agent_id, pipeline in self.data_agents.items():
            task = asyncio.create_task(pipeline.run(trigger_time))
            tasks.append((agent_id, task))

        results = []
        for agent_id, task in tasks:
            try:
                result = await task
                if result and result.get("context_string"):
                    results.append(result)
                    self._print_data_agent_result(result)
            except Exception as e:
                print(f"❌ Data Agent {agent_id} failed: {e}")

        return results

    async def _run_research_agents(
        self, trigger_time: str, data_factors: List
    ) -> List[Dict]:
        """Run all research agents in parallel"""
        tasks = []

        for agent_id, agent in self.research_agents.items():
            # Build background information for this agent
            background = agent.build_background_information(
                trigger_time, agent.config.belief, data_factors
            )

            input_data = ResearchAgentInput(
                trigger_time=trigger_time,
                background_information=background,
            )

            task = asyncio.create_task(agent.run(input_data))
            tasks.append((agent_id, agent, task))

        all_signals = []
        for agent_id, agent, task in tasks:
            try:
                result = await task
                if result and result.final_result:
                    # Parse signals from result
                    signals = self._parse_signals(result)

                    # Add agent metadata
                    for i, signal in enumerate(signals[:5]):  # Max 5 signals per agent
                        signal["agent_id"] = agent_id
                        signal["agent_name"] = agent.config.agent_name
                        signal["signal_index"] = i + 1
                        all_signals.append(signal)

                    if signals:
                        self._print_research_agent_result(agent.config.agent_name, signals)

            except Exception as e:
                print(f"❌ Research Agent {agent_id} failed: {e}")

        return all_signals

    def _parse_signals(self, result) -> List[Dict]:
        """Parse signals from research agent output"""
        thinking = result.final_result_thinking.split("<Output>")[0].strip()
        output = result.final_result.split("<Output>")[-1].strip()

        signals = []
        try:
            # Find all signal blocks
            signal_blocks = re.findall(r'<signal>(.*?)</signal>', output, flags=re.DOTALL)

            for signal_block in signal_blocks:
                try:
                    signal = self._parse_single_signal(signal_block, thinking)
                    if signal:
                        signals.append(signal)
                except Exception as e:
                    print(f"Error parsing individual signal: {e}")
                    continue

        except Exception as e:
            print(f"Error parsing signals: {e}")

        return signals

    def _parse_single_signal(self, signal_block: str, thinking: str) -> Dict:
        """Parse a single signal block"""
        try:
            has_opportunity = re.search(
                r"<has_opportunity>(.*?)</has_opportunity>", signal_block, flags=re.DOTALL
            ).group(1).strip()

            action = re.search(
                r"<action>(.*?)</action>", signal_block, flags=re.DOTALL
            ).group(1).strip()

            symbol_code = re.search(
                r"<symbol_code>(.*?)</symbol_code>", signal_block, flags=re.DOTALL
            ).group(1).strip()

            symbol_name = re.search(
                r"<symbol_name>(.*?)</symbol_name>", signal_block, flags=re.DOTALL
            ).group(1).strip()

            # Parse evidence list
            evidence_list_str = re.search(
                r"<evidence_list>(.*?)</evidence_list>", signal_block, flags=re.DOTALL
            ).group(1)

            evidence_list = []
            for item in evidence_list_str.split("<evidence>"):
                if '</evidence>' not in item:
                    continue

                evidence_description = item.split("</evidence>")[0].strip()

                try:
                    evidence_time = re.search(
                        r"<time>(.*?)</time>", item, flags=re.DOTALL
                    ).group(1).strip()
                except:
                    evidence_time = "N/A"

                try:
                    evidence_from_source = re.search(
                        r"<from_source>(.*?)</from_source>", item, flags=re.DOTALL
                    ).group(1).strip()
                except:
                    evidence_from_source = "N/A"

                evidence_list.append({
                    "description": evidence_description,
                    "time": evidence_time,
                    "from_source": evidence_from_source,
                })

            # Parse limitations (optional — LLM may omit this block)
            limitations_match = re.search(
                r"<limitations>(.*?)</limitations>", signal_block, flags=re.DOTALL
            )
            if limitations_match:
                limitations = [
                    l.strip()
                    for l in re.findall(
                        r"<limitation>(.*?)</limitation>", limitations_match.group(1), flags=re.DOTALL
                    )
                ]
            else:
                limitations = []

            # Parse probability
            probability = re.search(
                r"<probability>(.*?)</probability>", signal_block, flags=re.DOTALL
            ).group(1).strip()

            try:
                symbol_name, symbol_code = GLOBAL_MARKET_MANAGER.fix_symbol_code(
                    "CN-Stock", symbol_name, symbol_code
                )
            except Exception:
                pass

            return {
                "thinking": thinking,
                "has_opportunity": has_opportunity,
                "action": action,
                "symbol_code": symbol_code,
                "symbol_name": symbol_name,
                "evidence_list": evidence_list,
                "limitations": limitations,
                "probability": probability,
            }

        except Exception as e:
            print(f"Error parsing single signal: {e}")
            return None

    def _select_best_signals(self, research_signals: List[Dict]) -> List[Dict]:
        """
        Select best signals from all research agents.

        For now, just return all signals. Could implement more sophisticated
        selection logic (e.g., scoring, deduplication, etc.)
        """
        return research_signals

    def _print_data_agent_result(self, factor):
        """Print data agent result"""
        print(f"\n{'=' * 60}")
        print(f"✅ [{factor.get('agent_name')}] Data Factor Ready")
        print(f"{'=' * 60}")
        context = factor.get('context_string', '')
        summary = context[:300] if context else "(No content)"
        print(summary)
        if len(context) > 300:
            print("...")
        print(f"{'=' * 60}\n")

    def _print_research_agent_result(self, agent_name: str, signals: List[Dict]):
        """Print research agent result"""
        print(f"\n{'=' * 60}")
        print(f"✅ [{agent_name}] Research Signals Ready")
        print(f"{'=' * 60}")
        for i, signal in enumerate(signals, 1):
            symbol = signal.get("symbol_name") or signal.get("symbol_code") or "—"
            action = signal.get("action") or "—"
            print(f"{i}. {symbol} | {action}")
        print(f"{'=' * 60}\n")


async def main():
    """Main entry point for testing"""
    company = SimpleTradeCompany()

    # Use current time or specify a time
    trigger_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # trigger_time = "2024-01-23 09:00:00"  # For testing with specific time

    result = await company.run(trigger_time)

    print("\n" + "=" * 80)
    print("📊 Final Summary:")
    print(f"   Trigger Time: {result['trigger_time']}")
    print(f"   Data Factors: {len(result['data_factors'])}")
    print(f"   Research Signals: {len(result['research_signals'])}")
    print(f"   Best Signals: {len(result['best_signals'])}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

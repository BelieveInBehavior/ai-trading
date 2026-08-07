"""
Base Agent Loop Framework

A simplified agent architecture replacing LangGraph with explicit loop control.
Inspired by the ReAct pattern and Claude Code's agent loop implementation.
"""

import json
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path


@dataclass
class AgentLoopConfig:
    """Base configuration for agent loops"""
    agent_name: str
    max_iterations: int = 10
    max_context_tokens: int = 128000
    workspace_dir: Optional[Path] = None
    enable_cache: bool = True
    verbose: bool = True


class AgentLoopContext:
    """Manages agent execution context"""

    def __init__(self):
        self.steps: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {}

    def add_step(self, step_type: str, data: Dict[str, Any]):
        """Add a step to the context"""
        self.steps.append({
            "step_type": step_type,
            "iteration": len(self.steps),
            "data": data
        })

    def get_steps_by_type(self, step_type: str) -> List[Dict[str, Any]]:
        """Get all steps of a specific type"""
        return [step for step in self.steps if step["step_type"] == step_type]

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary"""
        return {
            "steps": self.steps,
            "metadata": self.metadata,
            "total_steps": len(self.steps)
        }


class BaseAgentLoop(ABC):
    """
    Base class for agent loop implementation.

    Replaces LangGraph's StateGraph with explicit loop control:

    while not should_terminate():
        result = execute_step()
        update_context(result)

    return finalize()
    """

    def __init__(self, config: AgentLoopConfig):
        self.config = config
        self.iteration = 0
        self.context = AgentLoopContext()
        self.result = None
        self._terminated = False

        # Setup workspace directory
        if config.workspace_dir:
            self.workspace_dir = Path(config.workspace_dir)
            self.workspace_dir.mkdir(parents=True, exist_ok=True)

    async def run(self, input_data: Any) -> Any:
        """
        Main execution loop.

        Args:
            input_data: Input data for the agent

        Returns:
            Final result from finalize()
        """
        try:
            # Initialize agent state
            await self.initialize(input_data)

            # Check if already have cached result
            if self.result is not None:
                if self.config.verbose:
                    print(f"[{self.config.agent_name}] Using cached result")
                return self.result

            # Main loop
            while not self.should_terminate():
                if self.config.verbose:
                    print(f"[{self.config.agent_name}] Iteration {self.iteration + 1}/{self.config.max_iterations}")

                # Execute one step
                step_result = await self.execute_step()

                # Update context
                self.update_context(step_result)

                # Increment iteration counter
                self.iteration += 1

            # Finalize and return result
            final_result = await self.finalize()

            if self.config.verbose:
                print(f"[{self.config.agent_name}] Completed after {self.iteration} iterations")

            return final_result

        except Exception as e:
            print(f"[{self.config.agent_name}] Error in run: {e}")
            import traceback
            traceback.print_exc()
            return await self.handle_error(e)

    @abstractmethod
    async def initialize(self, input_data: Any):
        """
        Initialize agent state before loop starts.

        This should:
        - Load cached results if available
        - Set up initial state variables
        - Perform any preprocessing

        Args:
            input_data: Input data for initialization
        """
        pass

    @abstractmethod
    async def execute_step(self) -> Dict[str, Any]:
        """
        Execute one iteration of the agent loop.

        This is the core logic that gets repeated.

        Returns:
            Dictionary containing step results and metadata
        """
        pass

    @abstractmethod
    def should_terminate(self) -> bool:
        """
        Determine if the loop should terminate.

        Common termination conditions:
        - Cached result already loaded
        - Max iterations reached
        - Context too long
        - Task completed (e.g., final_report tool selected)

        Returns:
            True if loop should terminate, False otherwise
        """
        pass

    @abstractmethod
    async def finalize(self) -> Any:
        """
        Finalize and return the result.

        This should:
        - Generate final output
        - Save to cache if enabled
        - Perform cleanup

        Returns:
            Final agent output
        """
        pass

    def update_context(self, step_result: Dict[str, Any]):
        """
        Update agent context with step result.

        Override this if you need custom context management.

        Args:
            step_result: Result from execute_step()
        """
        if step_result:
            self.context.add_step(
                step_type=step_result.get("action", "unknown"),
                data=step_result
            )

    async def handle_error(self, error: Exception) -> Any:
        """
        Handle errors during execution.

        Override this for custom error handling.

        Args:
            error: The exception that occurred

        Returns:
            Error result or None
        """
        return None

    def terminate(self):
        """Manually terminate the loop"""
        self._terminated = True

    def _check_basic_termination(self) -> bool:
        """Check basic termination conditions"""
        # Already have result
        if self.result is not None:
            return True

        # Max iterations reached
        if self.iteration >= self.config.max_iterations:
            if self.config.verbose:
                print(f"[{self.config.agent_name}] Max iterations ({self.config.max_iterations}) reached")
            return True

        # Manually terminated
        if self._terminated:
            return True

        return False

    def save_to_file(self, data: Dict[str, Any], filename: str):
        """Save data to workspace directory"""
        if not self.workspace_dir:
            return

        filepath = self.workspace_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if self.config.verbose:
            print(f"[{self.config.agent_name}] Saved to {filepath}")

    def load_from_file(self, filename: str) -> Optional[Dict[str, Any]]:
        """Load data from workspace directory"""
        if not self.workspace_dir:
            return None

        filepath = self.workspace_dir / filename
        if not filepath.exists():
            return None

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if self.config.verbose:
                print(f"[{self.config.agent_name}] Loaded from {filepath}")

            return data
        except Exception as e:
            print(f"[{self.config.agent_name}] Error loading from {filepath}: {e}")
            return None


class ReactAgentLoop(BaseAgentLoop):
    """
    ReAct (Reasoning + Acting) Agent Loop.

    Implements the ReAct pattern:
    1. Think: Select next tool/action
    2. Act: Execute the tool
    3. Observe: Record the result
    4. Repeat until done
    """

    def __init__(self, config: AgentLoopConfig):
        super().__init__(config)
        self.tool_calls: List[Dict[str, Any]] = []

    async def execute_step(self) -> Dict[str, Any]:
        """
        Execute one ReAct step: think → act → observe
        """
        # Think: Select tool
        selected_tool = await self.select_tool()

        # Check if final report
        if self.is_final_tool(selected_tool):
            return {
                "action": "finalize",
                "tool": selected_tool
            }

        # Act: Execute tool
        tool_result = await self.execute_tool(selected_tool)

        # Record tool call
        self.tool_calls.append({
            "iteration": self.iteration,
            "tool": selected_tool,
            "result": tool_result
        })

        # Return observation
        return {
            "action": "tool_call",
            "tool": selected_tool,
            "result": tool_result
        }

    @abstractmethod
    async def select_tool(self) -> Dict[str, Any]:
        """Select the next tool to execute"""
        pass

    @abstractmethod
    async def execute_tool(self, tool: Dict[str, Any]) -> Any:
        """Execute a selected tool"""
        pass

    def is_final_tool(self, tool: Dict[str, Any]) -> bool:
        """Check if tool is the final report tool"""
        return tool.get("tool_name") == "final_report"

    def get_tool_call_context(self) -> str:
        """Get formatted tool call history"""
        return json.dumps(self.tool_calls, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # Example usage
    class ExampleAgent(BaseAgentLoop):
        async def initialize(self, input_data):
            self.target = input_data.get("target", 10)
            self.current = 0

        async def execute_step(self):
            self.current += 1
            return {"action": "increment", "value": self.current}

        def should_terminate(self):
            if self._check_basic_termination():
                return True
            return self.current >= self.target

        async def finalize(self):
            return {"final_value": self.current, "target": self.target}

    async def test():
        config = AgentLoopConfig(agent_name="test_agent", max_iterations=100)
        agent = ExampleAgent(config)
        result = await agent.run({"target": 5})
        print(f"Result: {result}")

    asyncio.run(test())

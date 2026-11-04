"""
Hierarchical planner that decomposes goals into ordered sub-tasks.
Based on TDD Section 7.
"""

from enum import Enum
import json
import re
from typing import List, Optional
from agent.brain.brain_client import BrainClient
from agent.logger import logger


class PlannerState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"


class Planner:
    """Decomposes high-level user goals into sequential tasks and tracks progress."""

    def __init__(self, brain_client: BrainClient):
        self.brain = brain_client
        self.state = PlannerState.IDLE
        self.current_plan: List[str] = []
        self.current_step_index: int = 0

    async def plan_goal(self, goal: str) -> List[str]:
        """Decompose a high-level user goal into ordered steps."""
        self.state = PlannerState.PLANNING
        logger.info(f"[Planner] Generating task decomposition for: '{goal}'")

        prompt = f"""Break down this user desktop goal into 2 to 5 clear, sequential micro-steps.
User Goal: "{goal}"

Respond with ONLY a JSON array of strings, for example:
["Locate application icon", "Launch application", "Wait for window to focus", "Verify ready state"]"""

        raw = await self.brain.provider.generate(prompt=prompt, json_mode=True)
        try:
            cleaned = re.sub(r"^```(?:json)?", "", raw.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()
            tasks = json.loads(cleaned)
            if isinstance(tasks, list) and all(isinstance(t, str) for t in tasks):
                self.current_plan = tasks
                self.current_step_index = 0
                self.state = PlannerState.EXECUTING
                return tasks
        except Exception as e:
            logger.warning(f"[Planner] Could not parse task list from LLM: {e}, using heuristic decomposition.")

        # Heuristic fallback decomposition
        goal_lower = goal.lower()
        if "chrome" in goal_lower:
            tasks = ["Launch Google Chrome", "Wait for browser window", "Verify Chrome active"]
        elif "vs code" in goal_lower or "code" in goal_lower:
            tasks = ["Launch VS Code", "Wait for editor window", "Verify workspace ready"]
        else:
            tasks = [f"Initialize '{goal}'", f"Execute action for '{goal}'", "Verify completion"]

        self.current_plan = tasks
        self.current_step_index = 0
        self.state = PlannerState.EXECUTING
        return tasks

    def get_current_task(self) -> Optional[str]:
        """Return description of the current in-progress task."""
        if 0 <= self.current_step_index < len(self.current_plan):
            return self.current_plan[self.current_step_index]
        return None

    def advance_step(self) -> bool:
        """Advance to next task. Returns True if there are more steps, False if all complete."""
        self.current_step_index += 1
        if self.current_step_index >= len(self.current_plan):
            self.state = PlannerState.COMPLETED
            return False
        return True

    def reset(self) -> None:
        self.state = PlannerState.IDLE
        self.current_plan = []
        self.current_step_index = 0

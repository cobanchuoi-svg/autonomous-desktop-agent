"""
Teacher AI Module and Dataset Generator based on TDD Section 11 & 12.
Analyzes mistakes, formulates lessons, and exports fine-tuning datasets (JSONL, Alpaca, ShareGPT).
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from agent.brain.brain_client import BrainClient
from agent.memory.memory_manager import MemoryManager
from agent.logger import logger


class TeacherAI:
    """Evaluates action histories, identifies mistakes or slow execution, and synthesizes reusable lessons."""

    def __init__(self, brain_client: BrainClient, memory_manager: MemoryManager):
        self.brain = brain_client
        self.memory = memory_manager
        self.dataset_dir = Path("training_data")
        self.dataset_dir.mkdir(parents=True, exist_ok=True)

    async def analyze_failure(self, failed_action: Dict[str, Any], goal: str, screen_context: str) -> Optional[str]:
        """Analyze why an action failed and save a persistent lesson."""
        prompt = f"""You are a Teacher AI observing an agent's desktop automation failure.
Goal: {goal}
Failed Action: {failed_action}
Screen Context: {screen_context[:500]}

Extract ONE concise, generalizable rule or lesson that the agent should remember to avoid this mistake in the future.
Format your reply as a single sentence:
Lesson: <rule>"""

        response = await self.brain.provider.generate(prompt=prompt)
        lesson_text = response.replace("Lesson:", "").strip()
        if not lesson_text or len(lesson_text) < 5:
            lesson_text = f"Ensure element exists on screen before executing '{failed_action.get('action')}'."

        self.memory.add_lesson(lesson_text=lesson_text, confidence=0.85, source="teacher_ai")
        logger.info(f"[TeacherAI] Formulated new lesson: '{lesson_text}'")
        return lesson_text

    def export_dataset(self, filename: str = "agent_instructions", format_type: str = "alpaca") -> Path:
        """
        Export recorded successful actions as fine-tuning datasets (TDD Section 12).
        Formats: 'alpaca', 'sharegpt', 'jsonl'
        """
        actions = self.memory.get_recent_actions(limit=100)
        goal = self.memory.active_goal.title if self.memory.active_goal else "General desktop control"

        samples: List[Dict[str, Any]] = []

        for act in actions:
            if act.status != "success":
                continue

            instruction = f"Execute action to advance goal: {goal}"
            user_input = f"Action type: {act.action_type}"
            model_output = json.dumps({
                "action": act.action_type,
                "params": act.params,
                "result": act.result_message,
            })

            if format_type == "alpaca":
                samples.append({
                    "instruction": instruction,
                    "input": user_input,
                    "output": model_output,
                })
            elif format_type == "sharegpt":
                samples.append({
                    "conversations": [
                        {"from": "human", "value": f"{instruction}\n{user_input}"},
                        {"from": "gpt", "value": model_output},
                    ]
                })
            else:  # raw jsonl
                samples.append({
                    "goal": goal,
                    "action": act.action_type,
                    "params": act.params,
                    "status": act.status,
                })

        output_file = self.dataset_dir / f"{filename}_{format_type}.jsonl"
        with open(output_file, "w", encoding="utf-8") as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        logger.info(f"[TeacherAI] Exported {len(samples)} training samples to {output_file}")
        return output_file

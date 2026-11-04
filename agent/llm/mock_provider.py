"""
Deterministic Mock/Heuristic LLM Provider for unit testing and offline MVP dry-runs.
"""

import json
from typing import Optional
from agent.llm.base import BaseLLMProvider
from agent.logger import logger


class MockLLMProvider(BaseLLMProvider):
    """Fallback mock LLM that returns sensible structured JSON actions for testing."""

    def __init__(self, model_name: str = "mock-qwen-2b"):
        super().__init__(model_name=model_name, temperature=0.0, max_tokens=256)

    @property
    def provider_name(self) -> str:
        return "mock"

    async def health_check(self) -> bool:
        return True

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        logger.debug(f"[MockLLM] Generating action from prompt length: {len(prompt)}")

        # Check common goals in prompt
        prompt_lower = prompt.lower()
        if "chrome" in prompt_lower:
            action_data = {
                "thought": "User requested to open Chrome. I will launch Chrome via application controller.",
                "reason": "Chrome launch action fulfills the initial goal step.",
                "action": "launch_app",
                "params": {"app_name": "chrome"}
            }
        elif "vs code" in prompt_lower or "vscode" in prompt_lower or "code" in prompt_lower:
            action_data = {
                "thought": "User wants to open VS Code. Launching visual studio code.",
                "reason": "VS Code is requested in current goal.",
                "action": "launch_app",
                "params": {"app_name": "code"}
            }
        elif "click" in prompt_lower:
            action_data = {
                "thought": "Identified target element on screen. Performing click.",
                "reason": "Proceed with UI interaction.",
                "action": "click",
                "params": {"x": 500, "y": 300}
            }
        else:
            action_data = {
                "thought": "Observing environment to verify screen state.",
                "reason": "Wait for desktop response.",
                "action": "wait",
                "params": {"seconds": 1.0}
            }

        return json.dumps(action_data)

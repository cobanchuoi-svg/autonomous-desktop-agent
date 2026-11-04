"""
Backward-compatibility re-export for BrainClient.
Use `agent.brain.brain_client.BrainClient` for new code.
"""

from agent.brain.brain_client import BrainClient, QwenClient, SYSTEM_PROMPT

__all__ = ["BrainClient", "QwenClient", "SYSTEM_PROMPT"]

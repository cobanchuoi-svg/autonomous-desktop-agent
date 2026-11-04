"""
Core agent state representations and exceptions.
"""

from agent.core.state import AgentState, AgentStateMachine
from agent.core.exceptions import (
    AgentException,
    VisionException,
    OCRException,
    OCRUnavailableError,
    ActionExecutionException,
    SafetyViolationException,
    LLMInferenceException,
)

def __getattr__(name: str):
    if name == "AgentEngine":
        from agent.core.engine import AgentEngine
        return AgentEngine
    if name in ("Container", "container"):
        from agent.core.container import Container, container
        return Container if name == "Container" else container
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AgentState",
    "AgentStateMachine",
    "AgentException",
    "VisionException",
    "OCRException",
    "ActionExecutionException",
    "SafetyViolationException",
    "LLMInferenceException",
]

"""Shared structured models for desktop state and execution outcomes."""

from agent.models.desktop_state import DesktopState, DesktopStateManager
from agent.models.execution import Evidence, ExecutionResult, confidence_from_evidence

__all__ = [
    "DesktopState", "DesktopStateManager", "Evidence", "ExecutionResult",
    "confidence_from_evidence",
]

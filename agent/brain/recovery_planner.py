"""
Recovery Planner diagnosing runtime failures and producing alternative remediation strategies.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from agent.actions.base import ActionCommand, ActionType
from agent.logger import logger


class FailureType(str, Enum):
    OCR_FAILURE = "ocr_failure"
    VERIFICATION_FAILURE = "verification_failure"
    ACTION_FAILURE = "action_failure"
    TIMEOUT_FAILURE = "timeout_failure"
    UNKNOWN_FAILURE = "unknown_failure"


class RecoveryDiagnosis(BaseModel):
    failure_type: FailureType
    cause: str
    retry_count: int
    recommended_strategy: str
    remedial_actions: List[ActionCommand] = Field(default_factory=list)


class RecoveryPlanner:
    """Diagnoses failures and generates alternative action paths to recover interrupted goals."""

    def __init__(self, max_retries_per_step: int = 3):
        self.max_retries = max_retries_per_step
        self._step_retry_counts: Dict[str, int] = {}

    def diagnose_and_plan(
        self,
        failure_type: FailureType,
        error_message: str,
        current_goal: str,
        failed_command: Optional[ActionCommand] = None,
        step_identifier: str = "current_step",
    ) -> RecoveryDiagnosis:
        """Analyze failure cause and generate concrete fallback action sequence."""
        retries = self._step_retry_counts.get(step_identifier, 0) + 1
        self._step_retry_counts[step_identifier] = retries

        remedial_actions: List[ActionCommand] = []
        strategy = ""

        logger.warning(
            f"[RecoveryPlanner] Diagnosing {failure_type.value} on step '{step_identifier}' "
            f"(attempt {retries}/{self.max_retries}): {error_message}"
        )

        if failure_type == FailureType.OCR_FAILURE:
            strategy = "Wait for window redraw and refocus desktop."
            remedial_actions = [
                ActionCommand(action_type=ActionType.WAIT, params={"seconds": 1.0}),
                ActionCommand(action_type=ActionType.HOTKEY, params={"keys": ["alt", "tab"]}),
            ]

        elif failure_type == FailureType.VERIFICATION_FAILURE:
            # e.g. Pre-action target missing on taskbar
            cmd_type = failed_command.action_type if failed_command else ActionType.CLICK
            if cmd_type == ActionType.CLICK and "chrome" in current_goal.lower():
                strategy = "Taskbar click failed. Alternative strategy: Open Start menu, search 'chrome', and press Enter."
                remedial_actions = [
                    ActionCommand(action_type=ActionType.PRESS, params={"key": "win"}),
                    ActionCommand(action_type=ActionType.WAIT, params={"seconds": 0.5}),
                    ActionCommand(action_type=ActionType.WRITE, params={"text": "chrome", "interval": 0.05}),
                    ActionCommand(action_type=ActionType.PRESS, params={"key": "enter"}),
                ]
            elif cmd_type == ActionType.CLICK and ("code" in current_goal.lower() or "vscode" in current_goal.lower()):
                strategy = "Taskbar click failed. Alternative strategy: Launch VS Code via Start menu."
                remedial_actions = [
                    ActionCommand(action_type=ActionType.PRESS, params={"key": "win"}),
                    ActionCommand(action_type=ActionType.WAIT, params={"seconds": 0.5}),
                    ActionCommand(action_type=ActionType.WRITE, params={"text": "code", "interval": 0.05}),
                    ActionCommand(action_type=ActionType.PRESS, params={"key": "enter"}),
                ]
            else:
                strategy = "Target element obscured or shifted. Refresh view and cool down."
                remedial_actions = [
                    ActionCommand(action_type=ActionType.WAIT, params={"seconds": 1.5})
                ]

        elif failure_type == FailureType.ACTION_FAILURE:
            strategy = "OS action failed at driver level. Reset mouse/keyboard state."
            remedial_actions = [
                ActionCommand(action_type=ActionType.PRESS, params={"key": "esc"}),
                ActionCommand(action_type=ActionType.WAIT, params={"seconds": 1.0}),
            ]

        elif failure_type == FailureType.TIMEOUT_FAILURE:
            strategy = "Operation timed out. Press Escape and re-evaluate screen state."
            remedial_actions = [
                ActionCommand(action_type=ActionType.PRESS, params={"key": "esc"}),
                ActionCommand(action_type=ActionType.WAIT, params={"seconds": 1.0}),
            ]

        else:
            strategy = "General recovery: Cool down and re-observe."
            remedial_actions = [
                ActionCommand(action_type=ActionType.WAIT, params={"seconds": 1.0})
            ]

        return RecoveryDiagnosis(
            failure_type=failure_type,
            cause=error_message,
            retry_count=retries,
            recommended_strategy=strategy,
            remedial_actions=remedial_actions,
        )

    def reset_step(self, step_identifier: str) -> None:
        if step_identifier in self._step_retry_counts:
            del self._step_retry_counts[step_identifier]

    def reset_all(self) -> None:
        self._step_retry_counts.clear()

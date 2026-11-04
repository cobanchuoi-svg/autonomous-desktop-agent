"""
Coordinated Action Verifier uniting Pre-Action ROI checking and Post-Action State Validation.
Conforms to P0 #1 & #2 requirements.
"""

from typing import Optional
from PIL import Image
from agent.actions.base import ActionCommand, ActionResult, ActionType
from agent.verifier.roi_checker import ROIChecker, ROICheckResult
from agent.verifier.state_validator import StateValidator, StateValidationResult
from agent.logger import logger


class ActionVerifier:
    """Entry point for all pre-flight and post-flight action verification."""

    def __init__(
        self,
        roi_checker: Optional[ROIChecker] = None,
        state_validator: Optional[StateValidator] = None,
    ):
        self.roi_checker = roi_checker or ROIChecker()
        self.state_validator = state_validator or StateValidator()

    def verify_pre_action(self, command: ActionCommand, current_frame: Image.Image) -> ROICheckResult:
        """
        Verify target visibility and coordinates before physical execution.
        Prevents blind clicks caused by perception latency.
        """
        if command.action_type in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK, ActionType.MOVE):
            x = command.params.get("x")
            y = command.params.get("y")
            if x is not None and y is not None:
                return self.roi_checker.verify_target(current_frame, int(x), int(y))

        # Default pass for keyboard, wait, or application launches
        return ROICheckResult(
            is_valid=True,
            reason=f"Action '{command.action_type.value}' does not require coordinate ROI check",
            confidence=1.0,
        )

    def verify_post_action(
        self,
        command: ActionCommand,
        result: ActionResult,
        before_frame: Optional[Image.Image],
        after_frame: Optional[Image.Image],
        after_screen_text: Optional[str] = None,
    ) -> StateValidationResult:
        """Verify that the executed action actually achieved its visual purpose."""
        if not result.success:
            return StateValidationResult(
                is_valid=False,
                change_detected=False,
                reason=f"Action failed at execution layer: {result.error}",
            )

        target_identifier = command.params.get("app_name") or command.params.get("expected_text")
        return self.state_validator.validate_action_effect(
            before_frame=before_frame,
            after_frame=after_frame,
            action_type=command.action_type.value,
            expected_text=target_identifier,
            after_screen_text=after_screen_text,
        )

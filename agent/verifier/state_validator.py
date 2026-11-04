"""
Post-Action State Validator.
Verifies whether a desktop action caused the expected environmental or visual change.
"""

from typing import Dict, List, Optional
import re
import unicodedata
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field
from agent.logger import logger


class StateValidationResult(BaseModel):
    is_valid: bool
    change_detected: bool
    reason: str
    diff_score: float = 0.0


class StateValidator:
    """Compares pre-action and post-action visual states."""

    def __init__(self, change_threshold: float = 0.005):
        self.change_threshold = change_threshold

    def calculate_frame_diff(self, before: Image.Image, after: Image.Image) -> float:
        """Calculate normalized mean absolute difference between two frames."""
        try:
            b_arr = np.array(before.convert("L"), dtype=np.float32)
            a_arr = np.array(after.convert("L"), dtype=np.float32)

            if b_arr.shape != a_arr.shape:
                return 1.0  # Resolution change implies change

            diff = np.abs(b_arr - a_arr)
            # Fraction of pixels changed significantly (> 15 gray levels)
            significant_changes = np.count_nonzero(diff > 15)
            total_pixels = b_arr.size
            return float(significant_changes / total_pixels)
        except Exception as e:
            logger.error(f"[StateValidator] Frame diff error: {e}")
            return 0.0

    @staticmethod
    def text_matches_rule(expected_text: str, observed_text: str) -> bool:
        """Compare expected UI text with OCR output using a deterministic rule."""
        def normalize(value: str) -> str:
            folded = unicodedata.normalize("NFKD", value).casefold()
            without_marks = "".join(ch for ch in folded if not unicodedata.combining(ch))
            return " ".join(re.findall(r"[a-z0-9]+", without_marks))

        expected = normalize(expected_text)
        observed = normalize(observed_text)
        return bool(expected and observed and expected in observed)

    def validate_action_effect(
        self,
        before_frame: Optional[Image.Image],
        after_frame: Optional[Image.Image],
        action_type: str,
        expected_text: Optional[str] = None,
        after_screen_text: Optional[str] = None,
    ) -> StateValidationResult:
        """Validate whether action produced observable UI consequence."""
        # Non-visual or waiting actions always pass
        if action_type in ("wait", "read_file"):
            return StateValidationResult(
                is_valid=True,
                change_detected=False,
                reason=f"Action '{action_type}' does not require visual change",
                diff_score=0.0,
            )

        # Process launch verification
        if action_type == "launch_app":
            from agent.actions.application import ApplicationController
            app_ctrl = ApplicationController()
            target_proc = expected_text or "app"
            if target_proc and target_proc != "app":
                is_running = app_ctrl.is_process_running(target_proc)
                if not is_running:
                    return StateValidationResult(
                        is_valid=False,
                        change_detected=False,
                        reason=f"Goal validation failed: Target application '{target_proc}' was not launched or terminated immediately.",
                    )
                return StateValidationResult(
                    is_valid=True,
                    change_detected=True,
                    reason=f"Goal validation verified: Process '{target_proc}' is active in process table.",
                )

        # Text-based verification if expected text specified
        if expected_text and after_screen_text:
            if self.text_matches_rule(expected_text, after_screen_text):
                return StateValidationResult(
                    is_valid=True,
                    change_detected=True,
                    reason=f"Rule-based verification matched expected text '{expected_text}'",
                    diff_score=1.0,
                )

        # Image diff verification
        if before_frame is not None and after_frame is not None:
            diff = self.calculate_frame_diff(before_frame, after_frame)
            if diff >= self.change_threshold:
                return StateValidationResult(
                    is_valid=True,
                    change_detected=True,
                    reason=f"Visual mutation detected (diff score: {diff:.4f})",
                    diff_score=diff,
                )
            else:
                return StateValidationResult(
                    is_valid=False,
                    change_detected=False,
                    reason=f"No visual change detected following '{action_type}' (diff score: {diff:.4f})",
                    diff_score=diff,
                )

        return StateValidationResult(
            is_valid=True,
            change_detected=True,
            reason="Validation skipped (frames unavailable)",
            diff_score=0.0,
        )

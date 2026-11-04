"""
Pre-Action Region of Interest (ROI) Checker.
Verifies target coordinate validity and element visibility before action dispatch.
Solves P0 #1: Blind Action Execution.
"""

from typing import Dict, Optional, Tuple
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field
from agent.logger import logger


class ROICheckResult(BaseModel):
    is_valid: bool
    reason: str
    confidence: float = 1.0
    metrics: Dict[str, float] = Field(default_factory=dict)


class ROIChecker:
    """Samples and analyzes a bounding box patch around target coordinates."""

    def __init__(self, patch_size: int = 64, min_variance: float = 5.0):
        self.patch_size = patch_size
        self.min_variance = min_variance

    def extract_patch(self, image: Image.Image, x: int, y: int) -> Optional[Image.Image]:
        """Extract a square patch centered at (x, y)."""
        width, height = image.size
        half = self.patch_size // 2

        x1 = max(0, x - half)
        y1 = max(0, y - half)
        x2 = min(width, x + half)
        y2 = min(height, y + half)

        if x1 >= x2 or y1 >= y2:
            return None

        return image.crop((x1, y1, x2, y2))

    def verify_target(
        self,
        image: Image.Image,
        x: int,
        y: int,
        expected_label: Optional[str] = None,
    ) -> ROICheckResult:
        """
        Perform pre-flight verification at (x, y):
        1. Coordinate bounds check.
        2. Visual entropy/variance check (ensures target isn't solid blank / disabled overlay).
        """
        width, height = image.size

        # 1. Bounds check
        if x < 0 or x >= width or y < 0 or y >= height:
            return ROICheckResult(
                is_valid=False,
                reason=f"Target coordinate ({x}, {y}) is outside screen dimensions ({width}x{height})",
                confidence=0.0,
            )

        # 2. Extract patch
        patch = self.extract_patch(image, x, y)
        if patch is None:
            return ROICheckResult(
                is_valid=False,
                reason=f"Failed to crop ROI patch around ({x}, {y})",
                confidence=0.0,
            )

        # 3. Analyze variance (detect whether area is active UI or blank monochrome)
        patch_arr = np.array(patch.convert("L"))
        variance = float(np.var(patch_arr))

        if variance < self.min_variance:
            logger.warning(f"[ROIChecker] Low visual variance ({variance:.2f} < {self.min_variance}) at ({x}, {y})")
            return ROICheckResult(
                is_valid=False,
                reason=f"Target ROI has low visual detail (variance {variance:.1f}); element may be obscured or missing",
                confidence=0.3,
                metrics={"variance": variance},
            )

        return ROICheckResult(
            is_valid=True,
            reason=f"Target at ({x}, {y}) is visible and stable (variance: {variance:.1f})",
            confidence=0.95,
            metrics={"variance": variance},
        )

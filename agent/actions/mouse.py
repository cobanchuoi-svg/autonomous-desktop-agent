"""
Mouse controller leveraging PyAutoGUI with pynput integration.
"""

import time
from typing import Optional
from agent.actions.base import ActionResult, ActionType
from agent.core.exceptions import ActionExecutionException
from agent.logger import logger

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False


class MouseController:
    """Controls mouse movement, clicks, drags, and scrolling."""

    def __init__(self, move_duration: float = 0.2):
        self.move_duration = move_duration

    def click(self, x: int, y: int, button: str = "left") -> ActionResult:
        """Click at desktop coordinates (x, y)."""
        start = time.perf_counter()
        try:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.click(x=x, y=y, button=button, duration=self.move_duration)
            else:
                logger.info(f"[Mouse Simulation] Click at ({x}, {y}) button={button}")
            
            elapsed = time.perf_counter() - start
            return ActionResult(
                success=True,
                action_type=ActionType.CLICK,
                message=f"Clicked at ({x}, {y})",
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error(f"[MouseController] Click failed: {e}")
            return ActionResult(
                success=False,
                action_type=ActionType.CLICK,
                error=str(e),
                execution_time=elapsed,
            )

    def double_click(self, x: int, y: int) -> ActionResult:
        """Double click at desktop coordinates (x, y)."""
        start = time.perf_counter()
        try:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.doubleClick(x=x, y=y, duration=self.move_duration)
            else:
                logger.info(f"[Mouse Simulation] Double click at ({x}, {y})")

            elapsed = time.perf_counter() - start
            return ActionResult(
                success=True,
                action_type=ActionType.DOUBLE_CLICK,
                message=f"Double clicked at ({x}, {y})",
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start
            return ActionResult(
                success=False,
                action_type=ActionType.DOUBLE_CLICK,
                error=str(e),
                execution_time=elapsed,
            )

    def right_click(self, x: int, y: int) -> ActionResult:
        """Right click at desktop coordinates (x, y)."""
        return self.click(x=x, y=y, button="right")

    def move(self, x: int, y: int) -> ActionResult:
        """Move cursor smoothly to (x, y)."""
        start = time.perf_counter()
        try:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.moveTo(x=x, y=y, duration=self.move_duration)
            else:
                logger.info(f"[Mouse Simulation] Move to ({x}, {y})")

            elapsed = time.perf_counter() - start
            return ActionResult(
                success=True,
                action_type=ActionType.MOVE,
                message=f"Moved to ({x}, {y})",
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start
            return ActionResult(
                success=False,
                action_type=ActionType.MOVE,
                error=str(e),
                execution_time=elapsed,
            )

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> ActionResult:
        """Drag from (x1, y1) to (x2, y2)."""
        start = time.perf_counter()
        try:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.moveTo(x1, y1)
                pyautogui.dragTo(x2, y2, duration=duration, button="left")
            else:
                logger.info(f"[Mouse Simulation] Drag from ({x1}, {y1}) to ({x2}, {y2})")

            elapsed = time.perf_counter() - start
            return ActionResult(
                success=True,
                action_type=ActionType.DRAG,
                message=f"Dragged from ({x1}, {y1}) to ({x2}, {y2})",
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start
            return ActionResult(
                success=False,
                action_type=ActionType.DRAG,
                error=str(e),
                execution_time=elapsed,
            )

    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> ActionResult:
        """Scroll mouse wheel vertically."""
        start = time.perf_counter()
        try:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.scroll(clicks, x=x, y=y)
            else:
                logger.info(f"[Mouse Simulation] Scroll {clicks} clicks at ({x}, {y})")

            elapsed = time.perf_counter() - start
            return ActionResult(
                success=True,
                action_type=ActionType.SCROLL,
                message=f"Scrolled {clicks} clicks",
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start
            return ActionResult(
                success=False,
                action_type=ActionType.SCROLL,
                error=str(e),
                execution_time=elapsed,
            )

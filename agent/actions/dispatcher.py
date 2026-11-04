"""
Centralized ActionDispatcher with safety enforcement.
"""

import time
from typing import Optional
from agent.actions.base import ActionCommand, ActionResult, ActionType, BaseActionDispatcher
from agent.actions.safety import SafetyGuard
from agent.actions.mouse import MouseController
from agent.actions.keyboard import KeyboardController
from agent.actions.filesystem import FilesystemController
from agent.actions.application import ApplicationController
from agent.config import settings
from agent.logger import logger


class ActionDispatcher(BaseActionDispatcher):
    """Dispatches validated actions to the appropriate controller."""

    def __init__(self, safety_guard: Optional[SafetyGuard] = None):
        self.safety = safety_guard or SafetyGuard(settings.safety)
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.filesystem = FilesystemController()
        self.application = ApplicationController()

    def dispatch(self, command: ActionCommand) -> ActionResult:
        """Validate safety and execute the action."""
        start = time.perf_counter()

        # 1. Safety check
        is_allowed, reason, requires_approval = self.safety.validate(command)
        if not is_allowed:
            return ActionResult(
                success=False,
                action_type=command.action_type,
                error=f"Safety violation: {reason}",
                execution_time=time.perf_counter() - start,
            )

        if requires_approval:
            logger.warning(f"[ActionDispatcher] Action requires user approval: {command}")

        # 2. Routing to corresponding controller
        p = command.params
        t = command.action_type

        try:
            if t == ActionType.CLICK:
                return self.mouse.click(x=p.get("x", 0), y=p.get("y", 0), button=p.get("button", "left"))
            elif t == ActionType.DOUBLE_CLICK:
                return self.mouse.double_click(x=p.get("x", 0), y=p.get("y", 0))
            elif t == ActionType.RIGHT_CLICK:
                return self.mouse.right_click(x=p.get("x", 0), y=p.get("y", 0))
            elif t == ActionType.MOVE:
                return self.mouse.move(x=p.get("x", 0), y=p.get("y", 0))
            elif t == ActionType.DRAG:
                return self.mouse.drag(x1=p.get("x1", 0), y1=p.get("y1", 0), x2=p.get("x2", 0), y2=p.get("y2", 0))
            elif t == ActionType.SCROLL:
                return self.mouse.scroll(clicks=p.get("clicks", -1), x=p.get("x"), y=p.get("y"))
            elif t == ActionType.WRITE:
                return self.keyboard.write(text=p.get("text", ""), interval=p.get("interval", 0.05))
            elif t == ActionType.PRESS:
                return self.keyboard.press(key=p.get("key", "enter"))
            elif t == ActionType.HOTKEY:
                keys = p.get("keys", [])
                if isinstance(keys, str):
                    keys = [k.strip() for k in keys.split("+")]
                return self.keyboard.hotkey(*keys)
            elif t == ActionType.WAIT:
                duration = float(p.get("seconds", 1.0))
                time.sleep(duration)
                return ActionResult(
                    success=True,
                    action_type=ActionType.WAIT,
                    message=f"Waited {duration} seconds",
                    execution_time=time.perf_counter() - start,
                )
            elif t == ActionType.LAUNCH_APP:
                return self.application.launch_app(app_name=p.get("app_name", ""), args=p.get("args"))
            elif t == ActionType.KILL_APP:
                return self.application.kill_app(process_name=p.get("process_name", ""))
            elif t == ActionType.READ_FILE:
                return self.filesystem.read_file(path=p.get("path", ""))
            elif t == ActionType.WRITE_FILE:
                return self.filesystem.write_file(path=p.get("path", ""), content=p.get("content", ""))
            else:
                return ActionResult(
                    success=False,
                    action_type=t,
                    error=f"Unsupported action type: {t}",
                    execution_time=time.perf_counter() - start,
                )
        except Exception as e:
            logger.error(f"[ActionDispatcher] Unhandled exception in {t}: {e}")
            return ActionResult(
                success=False,
                action_type=t,
                error=str(e),
                execution_time=time.perf_counter() - start,
            )

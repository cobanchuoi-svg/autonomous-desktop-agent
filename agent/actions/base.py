"""
Base models and interfaces for desktop actions.
"""

from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ActionType(str, Enum):
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    MOVE = "move"
    DRAG = "drag"
    SCROLL = "scroll"
    WRITE = "write"
    PRESS = "press"
    HOTKEY = "hotkey"
    WAIT = "wait"
    LAUNCH_APP = "launch_app"
    KILL_APP = "kill_app"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"


class ActionCommand(BaseModel):
    """Command requesting a desktop action."""
    action_type: ActionType
    params: Dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None
    thought: Optional[str] = None


class ActionResult(BaseModel):
    """Result of executing an action."""
    success: bool
    action_type: ActionType
    message: str = ""
    error: Optional[str] = None
    execution_time: float = 0.0
    data: Optional[Dict[str, Any]] = None


from abc import ABC, abstractmethod


class BaseActionController(ABC):
    """Abstract interface for desktop action controllers."""
    pass


class BaseActionDispatcher(ABC):
    """Abstract interface for validating and dispatching actions."""

    @abstractmethod
    def dispatch(self, command: ActionCommand) -> ActionResult:
        """Validate safety and execute action command."""
        pass


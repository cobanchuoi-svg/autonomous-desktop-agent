"""
FSM Base State and StateType enumeration.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agent.core.fsm.context import StateContext


class StateType(str, Enum):
    IDLE = "IDLE"
    OBSERVE = "OBSERVE"
    RETRIEVE_MEMORY = "RETRIEVE_MEMORY"
    THINK = "THINK"
    VERIFY_ACTION = "VERIFY_ACTION"
    ACT = "ACT"
    VERIFY_RESULT = "VERIFY_RESULT"
    REMEMBER = "REMEMBER"
    RECOVERY = "RECOVERY"
    ERROR = "ERROR"
    SHUTDOWN = "SHUTDOWN"


class BaseState(ABC):
    """Abstract Base Class for all Finite State Machine states."""

    @property
    @abstractmethod
    def state_type(self) -> StateType:
        """The specific StateType identifier for this state."""
        pass

    @abstractmethod
    async def enter(self, context: "StateContext") -> None:
        """Executed immediately upon entering this state."""
        pass

    @abstractmethod
    async def execute(self, context: "StateContext") -> Optional[StateType]:
        """
        Main execution logic for this state.
        Returns the next StateType to transition to, or None to stay in current state.
        """
        pass

    @abstractmethod
    async def exit(self, context: "StateContext") -> None:
        """Executed immediately before transitioning away from this state."""
        pass

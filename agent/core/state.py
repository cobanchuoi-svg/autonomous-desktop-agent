"""
Agent State Machine and status representations based on TDD Section 7 & 9.
Flow: IDLE -> OBSERVE -> THINK -> ACT -> VERIFY -> (FAIL -> RECOVER) -> REMEMBER -> OBSERVE
"""

from enum import Enum
from typing import Callable, Dict, List, Optional
from agent.logger import logger


class AgentState(str, Enum):
    IDLE = "IDLE"
    OBSERVE = "OBSERVE"
    THINK = "THINK"
    ACT = "ACT"
    VERIFY = "VERIFY"
    RECOVER = "RECOVER"
    REMEMBER = "REMEMBER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class AgentStateMachine:
    """Manages state transitions and callbacks for the Desktop AI Agent."""

    # Valid transitions map
    TRANSITIONS: Dict[AgentState, List[AgentState]] = {
        AgentState.IDLE: [AgentState.OBSERVE, AgentState.STOPPED],
        AgentState.OBSERVE: [AgentState.THINK, AgentState.RECOVER, AgentState.STOPPED, AgentState.FAILED],
        AgentState.THINK: [AgentState.ACT, AgentState.COMPLETED, AgentState.FAILED, AgentState.RECOVER, AgentState.STOPPED],
        AgentState.ACT: [AgentState.VERIFY, AgentState.RECOVER, AgentState.FAILED, AgentState.STOPPED],
        AgentState.VERIFY: [AgentState.REMEMBER, AgentState.RECOVER, AgentState.COMPLETED, AgentState.STOPPED],
        AgentState.RECOVER: [AgentState.OBSERVE, AgentState.THINK, AgentState.FAILED, AgentState.STOPPED],
        AgentState.REMEMBER: [AgentState.OBSERVE, AgentState.COMPLETED, AgentState.STOPPED],
        AgentState.COMPLETED: [AgentState.IDLE],
        AgentState.FAILED: [AgentState.IDLE],
        AgentState.STOPPED: [AgentState.IDLE],
    }

    def __init__(self, initial_state: AgentState = AgentState.IDLE):
        self._current_state = initial_state
        self._listeners: List[Callable[[AgentState, AgentState], None]] = []

    @property
    def current_state(self) -> AgentState:
        return self._current_state

    def add_listener(self, listener: Callable[[AgentState, AgentState], None]) -> None:
        """Register a callback for state changes: func(old_state, new_state)."""
        self._listeners.append(listener)

    def transition_to(self, new_state: AgentState) -> bool:
        """Attempt to transition to a new state."""
        allowed = self.TRANSITIONS.get(self._current_state, [])
        if new_state not in allowed and new_state != AgentState.STOPPED:
            logger.warning(
                f"[StateMachine] Invalid transition: {self._current_state.value} -> {new_state.value}"
            )
            return False

        old_state = self._current_state
        self._current_state = new_state
        logger.info(f"[StateMachine] {old_state.value} -> {new_state.value}")

        for listener in self._listeners:
            try:
                listener(old_state, new_state)
            except Exception as e:
                logger.error(f"[StateMachine] Listener error: {e}")

        return True

    def reset(self) -> None:
        """Reset state machine to IDLE."""
        self._current_state = AgentState.IDLE

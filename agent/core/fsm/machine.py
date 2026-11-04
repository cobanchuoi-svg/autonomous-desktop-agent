"""
Finite State Machine Core orchestrator.
Replaces all while-true loops with a deterministic event-driven state driver.
Logs all transitions and persists state to SQLite for crash resilience.
"""

import asyncio
from typing import Callable, Dict, Optional
from agent.core.fsm.base import BaseState, StateType
from agent.core.fsm.context import StateContext
from agent.core.fsm.states import (
    ActState,
    ErrorState,
    IdleState,
    ObserveState,
    RecoveryState,
    RememberState,
    RetrieveMemoryState,
    ShutdownState,
    ThinkState,
    VerifyActionState,
    VerifyResultState,
)
from agent.logger import logger


class StateMachine:
    """Core state machine executing enter() -> execute() -> exit() cycles."""

    def __init__(self, context: StateContext, initial_state: StateType = StateType.IDLE):
        self.context = context
        self._states: Dict[StateType, BaseState] = {
            StateType.IDLE: IdleState(),
            StateType.OBSERVE: ObserveState(),
            StateType.RETRIEVE_MEMORY: RetrieveMemoryState(),
            StateType.THINK: ThinkState(),
            StateType.VERIFY_ACTION: VerifyActionState(),
            StateType.ACT: ActState(),
            StateType.VERIFY_RESULT: VerifyResultState(),
            StateType.REMEMBER: RememberState(),
            StateType.RECOVERY: RecoveryState(),
            StateType.ERROR: ErrorState(),
            StateType.SHUTDOWN: ShutdownState(),
        }

        self._current_state_type: StateType = initial_state
        self._current_state: BaseState = self._states[initial_state]
        self._is_running: bool = False
        self._transition_listeners: list[Callable[[StateType, StateType, str], None]] = []

    @property
    def current_state(self) -> StateType:
        return self._current_state_type

    def add_transition_listener(self, listener: Callable[[StateType, StateType, str], None]) -> None:
        """Register listener: cb(old_state, new_state, reason)."""
        self._transition_listeners.append(listener)

    async def transition_to(self, target_state_type: StateType, reason: str = "") -> None:
        """Perform orderly state transition: exit old -> persist -> log -> enter new."""
        old_state_type = self._current_state_type
        if old_state_type == target_state_type:
            return

        # 1. Exit current state
        await self._current_state.exit(self.context)

        # 2. Persist state snapshot to SQLite
        try:
            self.context.memory.save_agent_state(
                current_state=target_state_type.value,
                goal_id=self.context.goal_id,
                step_index=self.context.step_index,
                context_data=self.context.to_persisted_dict(),
            )
        except Exception as e:
            logger.error(f"[FSM] Failed to persist state transition to SQLite: {e}")

        # 3. Log transition
        logger.info(f"[FSM] Transition: {old_state_type.value} -> {target_state_type.value} (Reason: '{reason}')")
        self.context.notify(
            f"FSM: {old_state_type.value} -> {target_state_type.value} ({reason})",
            target_state_type.value,
        )

        for listener in self._transition_listeners:
            try:
                listener(old_state_type, target_state_type, reason)
            except Exception as e:
                logger.error(f"[FSM] Transition listener error: {e}")

        # 4. Enter new state
        self._current_state_type = target_state_type
        self._current_state = self._states[target_state_type]
        await self._current_state.enter(self.context)

    async def step(self) -> StateType:
        """Execute one state cycle. Returns current or newly transitioned state."""
        next_state = await self._current_state.execute(self.context)
        if next_state is not None and next_state != self._current_state_type:
            await self.transition_to(next_state, reason=f"Triggered by {self._current_state_type.value}.execute()")
        return self._current_state_type

    async def run(self, max_steps: Optional[int] = None) -> StateType:
        """
        Drive state transitions deterministically until IDLE, SHUTDOWN, or max_steps reached.
        Completely eliminates while-true loops.
        """
        self._is_running = True
        steps_executed = 0

        # Ensure initial state enter() has executed
        await self._current_state.enter(self.context)

        while self._is_running:
            if max_steps is not None and steps_executed >= max_steps:
                logger.warning(f"[FSM] Reached max_steps limit ({max_steps}). Goal incomplete.")
                self.context.is_goal_complete = False
                self.context.last_error = f"Halted: max_steps limit ({max_steps}) reached."
                await self.transition_to(StateType.ERROR, reason="max_steps_reached")
                break

            steps_executed += 1
            current = await self.step()

            # Terminal conditions
            if current in (StateType.SHUTDOWN, StateType.ERROR):
                logger.info(f"[FSM] Reached terminal state: {current.value}")
                self._is_running = False
                break

            if current == StateType.IDLE and self.context.is_goal_complete:
                logger.info("[FSM] Goal completed. Returning to IDLE.")
                self._is_running = False
                break

            await asyncio.sleep(0.01)

        self._is_running = False
        return self._current_state_type

    def stop(self) -> None:
        """Signal clean stop."""
        self._is_running = False
        self.context.should_shutdown = True

    async def resume_from_persisted(self) -> bool:
        """Load persisted state from SQLite and resume interrupted task."""
        saved = self.context.memory.load_agent_state()
        state_str = saved.get("current_state", "IDLE")
        if state_str in [s.value for s in StateType] and state_str not in ("IDLE", "SHUTDOWN"):
            target_state = StateType(state_str)
            ctx_data = saved.get("context", {})
            self.context.goal = ctx_data.get("goal", "")
            self.context.goal_id = saved.get("goal_id")
            self.context.step_index = saved.get("step_index", 0)
            self.context.current_task = ctx_data.get("current_task")

            logger.info(f"[FSM] Resuming interrupted task '{self.context.goal}' from persisted state: {target_state.value}")
            await self.transition_to(target_state, reason="resumed_from_persisted_sqlite")
            return True
        return False

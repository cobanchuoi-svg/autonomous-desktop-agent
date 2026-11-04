"""
Unit tests for Finite State Machine architecture and Recovery Planner.
"""

import tempfile
from pathlib import Path
from PIL import Image
import pytest

from agent.core.fsm.base import StateType
from agent.core.fsm.context import StateContext
from agent.core.fsm.machine import StateMachine
from agent.brain.recovery_planner import FailureType, RecoveryPlanner
from agent.llm.mock_provider import MockLLMProvider
from agent.brain.brain_client import BrainClient, QwenClient
from agent.memory.db import DatabaseManager
from agent.memory.memory_manager import MemoryManager


@pytest.mark.asyncio
async def test_fsm_initial_state():
    context = StateContext()
    fsm = StateMachine(context, initial_state=StateType.IDLE)
    assert fsm.current_state == StateType.IDLE


@pytest.mark.asyncio
async def test_fsm_transitions_and_enter_exit():
    transitions = []

    def on_trans(old, new, reason):
        transitions.append((old, new))

    context = StateContext()
    fsm = StateMachine(context, initial_state=StateType.IDLE)
    fsm.add_transition_listener(on_trans)

    await fsm.transition_to(StateType.OBSERVE, reason="Testing observe transition")
    assert fsm.current_state == StateType.OBSERVE
    assert len(transitions) == 1
    assert transitions[0] == (StateType.IDLE, StateType.OBSERVE)


@pytest.mark.asyncio
async def test_recovery_routing_on_verification_failure():
    """Verify that Recovery Planner is the default transition target upon failure."""
    context = StateContext()
    # Mock pre-verification failure
    context.last_error = "Target ROI has low variance / obscured"
    context.failure_type = FailureType.VERIFICATION_FAILURE

    fsm = StateMachine(context, initial_state=StateType.VERIFY_ACTION)
    # Executing VerifyActionState without valid coordinates should route to RECOVERY
    next_state = await fsm.step()
    assert next_state == StateType.RECOVERY


@pytest.mark.asyncio
async def test_recovery_planner_alternative_strategy():
    planner = RecoveryPlanner()
    diagnosis = planner.diagnose_and_plan(
        failure_type=FailureType.VERIFICATION_FAILURE,
        error_message="Taskbar icon not visible",
        current_goal="Open Chrome",
    )
    assert diagnosis.failure_type == FailureType.VERIFICATION_FAILURE
    assert len(diagnosis.remedial_actions) > 0
    # Expected strategy uses Start Menu
    assert "Start menu" in diagnosis.recommended_strategy


@pytest.mark.asyncio
async def test_fsm_state_persistence_and_resume():
    """Verify current state is persisted to SQLite and can be resumed after restart."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "fsm_test.db"
        mem = MemoryManager(DatabaseManager(str(db_path)))

        context = StateContext(memory=mem)
        context.goal = "Open VS Code"
        goal = mem.create_goal("Open VS Code")
        context.goal_id = goal.id
        context.step_index = 2

        fsm = StateMachine(context, initial_state=StateType.IDLE)
        # Transition to ACT -> triggers save_agent_state
        await fsm.transition_to(StateType.ACT, reason="Executing action")

        # Create a new FSM instance simulating process restart
        context2 = StateContext(memory=mem)
        fsm2 = StateMachine(context2, initial_state=StateType.IDLE)
        resumed = await fsm2.resume_from_persisted()

        assert resumed is True
        assert fsm2.current_state == StateType.ACT
        assert context2.goal == "Open VS Code"
        assert context2.step_index == 2

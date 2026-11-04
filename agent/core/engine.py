"""
Central AgentEngine coordinating the autonomous desktop agent using the Finite State Machine.
Replaces all while-true loops with the deterministic StateMachine.
"""

import asyncio
from typing import AsyncIterator, Callable, List, Optional

from agent.config import AppConfig, settings
from agent.core.exceptions import OCRUnavailableError
from agent.core.fsm.base import StateType
from agent.core.fsm.context import StateContext
from agent.core.fsm.machine import StateMachine
from agent.memory.memory_manager import MemoryManager
from agent.vision.capture import ScreenCapture
from agent.vision.base import BaseOCRProcessor
from agent.vision.factory import create_ocr_processor
from agent.brain.brain_client import BrainClient, QwenClient
from agent.brain.planner import Planner
from agent.brain.teacher import TeacherAI
from agent.brain.recovery_planner import RecoveryPlanner
from agent.verifier.action_verifier import ActionVerifier
from agent.actions import ActionDispatcher
from agent.actions.base import ActionCommand, ActionResult, ActionType
from agent.actions.application import ApplicationController
from agent.actions.ui_automation import WindowsUIAutomationController
from agent.logger import logger
from agent.core.benchmark import Benchmark
from agent.decision.goal_classifier import GoalClassifier
from agent.decision.module_router import ModuleRouter
from agent.models.execution import Evidence, ExecutionResult, confidence_from_evidence


class AgentEngine:
    """Orchestrates perception, reasoning, verification, action, and recovery via the FSM."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        brain_client: Optional[BrainClient] = None,
        qwen_client: Optional[BrainClient] = None,
        memory_manager: Optional[MemoryManager] = None,
        screen_capture: Optional[ScreenCapture] = None,
        ocr_processor: Optional[BaseOCRProcessor] = None,
        dispatcher: Optional[ActionDispatcher] = None,
        verifier: Optional[ActionVerifier] = None,
        recovery_planner: Optional[RecoveryPlanner] = None,
    ):
        self.config = config or settings
        self.memory = memory_manager or MemoryManager()
        self.capture = screen_capture or ScreenCapture()
        self.ocr = ocr_processor or create_ocr_processor(self.config.ocr_engine)
        self.dispatcher = dispatcher or ActionDispatcher()
        self.verifier = verifier or ActionVerifier()
        self.recovery_planner = recovery_planner or RecoveryPlanner()
        self.brain_client = brain_client or qwen_client
        self.qwen_client = self.brain_client
        self.router = ModuleRouter()
        self.last_execution_result: Optional[ExecutionResult] = None
        self._benchmark = Benchmark()
        self._workflow_runtime = None

        # Build FSM Context
        self.context = StateContext(
            config=self.config,
            memory=self.memory,
            capture=self.capture,
            ocr=self.ocr,
            brain=self.brain_client,
            dispatcher=self.dispatcher,
            verifier=self.verifier,
            recovery_planner=self.recovery_planner,
        )

        # FSM Core
        self.fsm = StateMachine(self.context, initial_state=StateType.IDLE)
        self._step_callbacks: List[Callable[[str, str], None]] = []

        # Wire callbacks
        self.context.listeners.append(self._on_context_event)
        self.fsm.add_transition_listener(self._on_transition)

    def add_step_callback(self, cb: Callable[[str, str], None]) -> None:
        """Register callback for UI updates: cb(log_message, current_state_name)."""
        self._step_callbacks.append(cb)

    def _on_context_event(self, message: str, state_name: str) -> None:
        for cb in self._step_callbacks:
            try:
                cb(message, state_name)
            except Exception:
                pass

    def _on_transition(self, old_state: StateType, new_state: StateType, reason: str) -> None:
        msg = f"[FSM Transition] {old_state.value} -> {new_state.value} (Reason: {reason})"
        for cb in self._step_callbacks:
            try:
                cb(msg, new_state.value)
            except Exception:
                pass

    async def initialize(self) -> None:
        """Initialize brain subsystems if not already configured."""
        # Fail early if OCR is unavailable: do not permit autonomous execution on synthetic/missing vision
        if hasattr(self.ocr, "is_available") and not self.ocr.is_available():
            raise OCRUnavailableError(
                f"Configured OCR backend '{self.config.ocr_engine}' is not installed or available. "
                "Desktop perception cannot continue until that backend's dependencies are installed."
            )

        if self.context.brain is None:
            from agent.llm.factory import create_llm_provider
            provider = await create_llm_provider(self.config.llm)
            self.context.brain = BrainClient(provider)
            self.brain_client = self.context.brain
            self.qwen_client = self.brain_client

        if self.context.planner is None:
            self.context.planner = Planner(self.context.brain)

        if self.context.teacher is None:
            self.context.teacher = TeacherAI(self.context.brain, self.memory)

        logger.info(f"[AgentEngine] Subsystems online. Provider: {self.context.brain.provider.provider_name}")

    async def stream_chat(self, message: str) -> AsyncIterator[str]:
        """Stream a plain chat answer without initializing OCR, planner, or FSM."""
        if self.context.brain is None:
            from agent.llm.factory import create_llm_provider

            provider = await create_llm_provider(self.config.llm)
            self.context.brain = BrainClient(provider)
            self.brain_client = self.context.brain
            self.qwen_client = self.brain_client

        async for token in self.context.brain.provider.generate_stream(
            prompt=message,
            system_prompt=(
                "You are a helpful local desktop assistant. Answer the user's question "
                "clearly and directly. Do not claim to have performed desktop actions."
            ),
            json_mode=False,
        ):
            yield token

    async def process_request(self, message: str, on_chat_start=None, on_chat_token=None):
        """Route a chat request through the registered V2 workflows, without starting OCR/FSM by default."""
        if self.context.brain is None:
            from agent.llm.factory import create_llm_provider

            provider = await create_llm_provider(self.config.llm)
            self.context.brain = BrainClient(provider)
            self.brain_client = self.context.brain
            self.qwen_client = self.brain_client
        if self._workflow_runtime is None:
            from agent.core.container import container
            from agent.workflows.runtime import WorkflowRuntime

            self._workflow_runtime = WorkflowRuntime(
                provider=self.context.brain.provider,
                engine=self,
                plugin_manager=container.plugin_manager,
                gemini_enabled=self.config.gemini_cli_enabled,
                gemini_timeout=self.config.gemini_cli_timeout,
                gemini_model=self.config.gemini_cli_model,
            )
        return await self._workflow_runtime.handle(message, on_chat_start, on_chat_token)

    async def propose_workflow(self, request: str):
        """Create a pending workflow candidate from registered workflows; this does not activate it."""
        if self.context.qwen is None:
            from agent.llm.factory import create_llm_provider

            provider = await create_llm_provider(self.config.llm)
            self.context.qwen = QwenClient(provider)
            self.qwen_client = self.context.qwen
        from agent.workflows.designer import WorkflowDesigner

        runtime = self._workflow_runtime
        if runtime is None:
            from agent.workflows.runtime import WorkflowRuntime
            runtime = WorkflowRuntime(
                self.context.qwen.provider,
                self,
                gemini_enabled=self.config.gemini_cli_enabled,
                gemini_timeout=self.config.gemini_cli_timeout,
                gemini_model=self.config.gemini_cli_model,
            )
            self._workflow_runtime = runtime
        return await WorkflowDesigner(self.context.qwen.provider, runtime.registry).propose(request)

    async def approve_workflow(self, candidate_id: str):
        """Explicitly approve a saved candidate for future routing."""
        if self.context.qwen is None:
            from agent.llm.factory import create_llm_provider

            provider = await create_llm_provider(self.config.llm)
            self.context.qwen = QwenClient(provider)
            self.qwen_client = self.context.qwen
        from agent.workflows.designer import WorkflowDesigner
        runtime = self._workflow_runtime
        if runtime is None:
            from agent.workflows.runtime import WorkflowRuntime
            runtime = WorkflowRuntime(
                self.context.qwen.provider,
                self,
                gemini_enabled=self.config.gemini_cli_enabled,
                gemini_timeout=self.config.gemini_cli_timeout,
                gemini_model=self.config.gemini_cli_model,
            )
            self._workflow_runtime = runtime
        return WorkflowDesigner(runtime.provider, runtime.registry).approve(candidate_id)

    @classmethod
    def known_application_for_goal(cls, goal: str) -> Optional[tuple[str, str]]:
        """Match launch-only requests for supported apps; leave compound goals to the planner."""
        return GoalClassifier.known_application_for_goal(goal)

    def _set_execution_result(
        self, goal: str, success: bool, route: str, reason: str = "",
        evidence: Optional[List[Evidence]] = None, error: Optional[str] = None,
    ) -> None:
        evidence = evidence or []
        self.last_execution_result = ExecutionResult(
            goal=goal,
            success=success,
            route=route,
            reason=reason,
            evidence=evidence,
            confidence=confidence_from_evidence(evidence, fallback=0.0),
            timings=self._benchmark.snapshot(),
            error=error,
        )

    async def _run_known_application_goal(
        self, goal: str, app_name: str, process_name: str
    ) -> bool:
        """Launch and process-verify a known app without OCR or planner steps."""
        self.context.goal = goal
        self.context.step_index = 0
        self.context.is_goal_complete = False
        self.context.should_shutdown = False

        active_goal = self.memory.get_active_goal()
        if active_goal and active_goal.title.strip().casefold() == goal.strip().casefold():
            goal_id = active_goal.id
        else:
            goal_id = self.memory.create_goal(goal).id
        self.context.goal_id = goal_id

        command = ActionCommand(
            action_type=ActionType.LAUNCH_APP,
            params={"app_name": app_name},
            reason="Known application launch fast path",
        )
        self.context.proposed_action = command

        with self._benchmark.measure("action_dispatch"):
            result = await asyncio.to_thread(self.dispatcher.dispatch, command)
        self.context.action_result = result
        with self._benchmark.measure("process_verification"):
            process_running = await asyncio.to_thread(
                ApplicationController().is_process_running, process_name
            )
        result.data = dict(result.data or {}, process_running=process_running)
        result.success = process_running
        if not process_running:
            result.error = result.error or f"Process '{process_name}' was not found after launch."
        elif not result.message:
            result.message = f"Verified running process '{process_name}'."

        self.memory.record_action(
            action_type=ActionType.LAUNCH_APP.value,
            params=command.params,
            status="success" if result.success else "failure",
            result_message=result.message or result.error or "",
            goal_id=goal_id,
        )

        if not result.success:
            self.context.last_error = result.error or f"Failed to launch {app_name}."
            evidence = [Evidence(
                kind="process_running", value=False, source="process_table", confidence=0.99,
            )]
            self._set_execution_result(
                goal, False, "application_launcher", self.context.last_error,
                evidence=evidence, error=self.context.last_error,
            )
            logger.error(f"[AgentEngine] Fast-path launch failed: {self.context.last_error}")
            return False

        self.memory.complete_goal(goal_id)
        self.context.is_goal_complete = True
        self.context.last_error = None
        evidence = [Evidence(
            kind="process_running", value=True, source="process_table", confidence=0.99,
        )]
        self._set_execution_result(
            goal, True, "application_launcher",
            f"Verified process '{process_name}' is running.", evidence=evidence,
        )
        logger.info(
            f"[AgentEngine] Fast-path goal '{goal}' completed; verified process '{process_name}'."
        )
        return True

    async def _run_search_app_goal(self, goal: str, app_name: str) -> bool:
        """Open an installed app from Windows Search and require observable verification."""
        self.context.goal = goal
        self.context.step_index = 0
        self.context.is_goal_complete = False
        self.context.should_shutdown = False
        goal_id = self.memory.create_goal(goal).id
        self.context.goal_id = goal_id

        with self._benchmark.measure("windows_search_launch"):
            result = await asyncio.to_thread(
                WindowsUIAutomationController().open_app_from_search, app_name
            )
        self.context.action_result = result
        self.memory.record_action(
            action_type=ActionType.LAUNCH_APP.value,
            params={"app_name": app_name, "method": "windows_search_uia"},
            status="success" if result.success else "failure",
            result_message=result.message or result.error or "",
            goal_id=goal_id,
        )

        evidence = [Evidence(
            kind="app_search_verification",
            value=bool(result.data and result.data.get("verified")),
            source="windows_search_uia",
            confidence=0.98 if result.success else 0.95,
        )]
        if not result.success:
            self.context.last_error = result.error
            self._set_execution_result(
                goal, False, "windows_search_launcher", result.error or f"'{app_name}' was not verified.",
                evidence=evidence, error=result.error,
            )
            logger.warning(f"[AgentEngine] Windows Search app route failed: {result.error}")
            return False

        self.memory.complete_goal(goal_id)
        self.context.is_goal_complete = True
        self.context.last_error = None
        self._set_execution_result(
            goal, True, "windows_search_launcher", result.message, evidence=evidence,
        )
        logger.info(f"[AgentEngine] App '{app_name}' opened and verified through Windows Search.")
        return True

    async def run_goal(self, goal: str, max_steps: int = 25) -> bool:
        """
        Execute goal via deterministic FSM transitions.
        No while-true loop: the StateMachine drives all state transitions.
        """
        self._benchmark = Benchmark()
        self.context.benchmark = self._benchmark
        with self._benchmark.measure("module_routing"):
            route = self.router.route(goal)
        if route.module == "windows_search_launcher":
            app_name = route.application[0] if route.application else ""
            return await self._run_search_app_goal(goal, app_name)
        if route.module == "application_launcher":
            app_name, process_name = GoalClassifier.known_application_for_goal(goal) or ("", "")
            return await self._run_known_application_goal(goal, app_name, process_name)

        with self._benchmark.measure("initialize"):
            await self.initialize()

        # Check for interrupted task to resume
        if not goal:
            resumed = await self.fsm.resume_from_persisted()
            if resumed:
                with self._benchmark.measure("fsm_run"):
                    terminal_state = await self.fsm.run(max_steps=max_steps)
                success = terminal_state == StateType.IDLE and self.context.is_goal_complete
                self._set_execution_result(
                    goal, success, "fsm", "Resumed persisted goal.",
                    evidence=[Evidence("fsm_goal_complete", success, "fsm", 0.9 if success else 0.5)],
                    error=self.context.last_error,
                )
                return success

        # Setup goal in working memory & context
        self.context.goal = goal
        created_goal = self.memory.create_goal(goal)
        self.context.goal_id = created_goal.id
        self.context.step_index = 0
        self.context.is_goal_complete = False
        self.context.should_shutdown = False

        # Transition to OBSERVE to start loop
        await self.fsm.transition_to(StateType.OBSERVE, reason=f"Started new goal: '{goal}'")

        # Drive FSM
        with self._benchmark.measure("fsm_run"):
            terminal_state = await self.fsm.run(max_steps=max_steps)
        if not self.context.is_goal_complete:
            self._set_execution_result(
                goal, False, "fsm", f"FSM stopped in {terminal_state.value} before completion.",
                evidence=[Evidence("fsm_goal_complete", False, "fsm", 0.9)],
                error=self.context.last_error,
            )
            logger.warning(f"[AgentEngine] Goal '{goal}' was not completed (Terminal state: {terminal_state.value}).")
            return False

        self._set_execution_result(
            goal, True, "fsm", "FSM marked the goal complete.",
            evidence=[Evidence("fsm_goal_complete", True, "fsm", 0.9)],
        )
        logger.info(f"[AgentEngine] Goal '{goal}' verified completed successfully.")
        return True

    def stop(self) -> None:
        """Request immediate agent shutdown."""
        self.fsm.stop()
        logger.info("[AgentEngine] Stop requested by user.")

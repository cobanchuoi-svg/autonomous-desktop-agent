"""
Implementation of all 11 concrete FSM states.
Every state implements enter(), execute(), and exit().
"""

import asyncio
from typing import Optional
from PIL import Image

from agent.core.fsm.base import BaseState, StateType
from agent.core.fsm.context import StateContext
from agent.core.exceptions import OCRUnavailableError
from agent.brain.recovery_planner import FailureType
from agent.actions.base import ActionCommand, ActionType
from agent.logger import logger
from agent.vision.element_selector import TextTargetSelector


class IdleState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.IDLE

    async def enter(self, context: StateContext) -> None:
        context.notify("Entering IDLE state. Awaiting goal or resume signal.", self.state_type.value)

    async def execute(self, context: StateContext) -> Optional[StateType]:
        if context.should_shutdown:
            return StateType.SHUTDOWN

        if context.goal and not context.is_goal_complete:
            context.notify(f"Goal received: '{context.goal}'. Proceeding to OBSERVE.", self.state_type.value)
            return StateType.OBSERVE

        # Remain in IDLE awaiting input
        await asyncio.sleep(0.2)
        return None

    async def exit(self, context: StateContext) -> None:
        context.notify("Exiting IDLE state.", self.state_type.value)


class ObserveState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.OBSERVE

    async def enter(self, context: StateContext) -> None:
        context.notify("Entering OBSERVE state: Capturing screen and running OCR.", self.state_type.value)

    async def execute(self, context: StateContext) -> Optional[StateType]:
        try:
            # 1. Screen capture
            with context.benchmark.measure("screen_capture"):
                frame = await asyncio.to_thread(context.capture.capture_frame)
            context.current_frame = frame

            # 2. OCR and accessible controls are independent observations of the same frame.
            async def read_ocr():
                with context.benchmark.measure("ocr_total"):
                    return await asyncio.to_thread(context.ocr.extract_text, frame)

            async def read_accessibility():
                with context.benchmark.measure("uia_perception"):
                    return await asyncio.to_thread(context.ui_automation.get_foreground_controls)

            ocr_result, accessible_elements = await asyncio.gather(
                read_ocr(), read_accessibility()
            )
            # OCR may be fast while the PowerShell/UIA probe is slow.  Record
            # the two timings separately so observation latency is diagnosable.
            timings = context.benchmark.snapshot()
            ocr_seconds = timings.get("ocr_total", 0.0)
            uia_seconds = timings.get("uia_perception", 0.0)
            logger.debug(
                f"[ObserveState] perception timing: OCR={ocr_seconds:.3f}s UIA={uia_seconds:.3f}s"
            )
            if uia_seconds > 0.75:
                logger.warning(
                    f"[ObserveState] UI Automation was slow ({uia_seconds:.3f}s); "
                    f"OCR was {ocr_seconds:.3f}s."
                )
            context.ocr_result = ocr_result
            context.screen_text = ocr_result.get("full_text", "")
            context.desktop_state = context.desktop_state_manager.update(
                frame, ocr_result, accessible_elements
            )
            context.memory.update_short_term(screen_text=context.screen_text)

            context.notify(
                f"Observation complete: {len(ocr_result.get('elements', []))} UI elements detected.",
                self.state_type.value,
            )
            return StateType.RETRIEVE_MEMORY

        except OCRUnavailableError as e:
            logger.critical(f"[ObserveState] OCR subsystem is unavailable: {e}")
            context.last_error = str(e)
            context.failure_type = FailureType.OCR_FAILURE
            return StateType.ERROR

        except Exception as e:
            logger.error(f"[ObserveState] Capture/OCR failed: {e}")
            context.last_error = str(e)
            context.failure_type = FailureType.OCR_FAILURE
            return StateType.RECOVERY

    async def exit(self, context: StateContext) -> None:
        if context.current_frame:
            context.before_frame = context.current_frame.copy()


class RetrieveMemoryState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.RETRIEVE_MEMORY

    async def enter(self, context: StateContext) -> None:
        context.notify("Entering RETRIEVE_MEMORY state: Querying relevant knowledge.", self.state_type.value)

    async def execute(self, context: StateContext) -> Optional[StateType]:
        try:
            recent_acts = [a.model_dump() for a in context.memory.get_recent_actions(limit=5)]
            relevant_entries = context.retrieval.retrieve_relevant(
                goal=context.goal,
                screen_text=context.screen_text,
                recent_actions=recent_acts,
                limit=3,
            )
            context.retrieved_memories = [m.content for m in relevant_entries]
            context.notify(
                f"Retrieved {len(context.retrieved_memories)} relevant memories.",
                self.state_type.value,
            )
            return StateType.THINK
        except Exception as e:
            logger.warning(f"[RetrieveMemoryState] Memory retrieval error: {e}, using empty context.")
            context.retrieved_memories = []
            return StateType.THINK

    async def exit(self, context: StateContext) -> None:
        pass


class ThinkState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.THINK

    async def enter(self, context: StateContext) -> None:
        context.notify("Entering THINK state: Planning next action candidate.", self.state_type.value)

    async def execute(self, context: StateContext) -> Optional[StateType]:
        try:
            # Initialize planner if needed
            if context.planner is None and context.brain is not None:
                from agent.brain.planner import Planner
                context.planner = Planner(context.brain)

            # Decompose goal into subtasks if needed
            if context.planner and not context.planner.current_plan:
                with context.benchmark.measure("goal_decomposition"):
                    subtasks = await context.planner.plan_goal(context.goal)
                context.memory.set_tasks_for_goal(context.goal_id, subtasks)  # type: ignore
                context.current_task = context.planner.get_current_task()

            assert context.brain is not None
            recent_acts = [a.model_dump() for a in context.memory.get_recent_actions(limit=5)]
            selected_elements = TextTargetSelector().select(
                goal=context.goal,
                current_task=context.current_task or "",
                elements=context.desktop_state.available_objects,
            )
            ui_elements = [element.model_dump() for element in selected_elements]
            selected_screen_text = " | ".join(
                dict.fromkeys(element.text for element in selected_elements)
            )
            if not selected_screen_text:
                selected_screen_text = context.screen_text[:1200]

            # Generate structured JSON action
            with context.benchmark.measure("action_reasoning"):
                action_resp = await context.brain.generate_action(
                    goal=context.goal,
                    screen_text=selected_screen_text,
                    memories=context.retrieved_memories,
                    previous_actions=recent_acts,
                    current_task=context.current_task,
                    ui_elements=ui_elements,
                )

            cmd_type = ActionType(action_resp.action.lower()) if action_resp.action.lower() in [e.value for e in ActionType] else ActionType.WAIT
            params = dict(action_resp.params)
            element_id = params.get("element_id")
            if element_id:
                coordinates = context.desktop_state_manager.coordinate_registry.resolve(
                    str(element_id), context.desktop_state.screen_hash
                )
                if coordinates is None:
                    raise ValueError(f"LLM selected unknown UI element id: {element_id}")
                params["x"] = coordinates.center[0]
                params["y"] = coordinates.center[1]
            context.proposed_action = ActionCommand(
                action_type=cmd_type,
                params=params,
                thought=action_resp.thought,
                reason=action_resp.reason,
            )

            context.notify(
                f"Thought: '{action_resp.thought}' -> Proposed Action: '{cmd_type.value}'",
                self.state_type.value,
            )
            return StateType.VERIFY_ACTION

        except asyncio.TimeoutError:
            context.last_error = "LLM thinking timed out."
            context.failure_type = FailureType.TIMEOUT_FAILURE
            return StateType.RECOVERY
        except Exception as e:
            logger.error(f"[ThinkState] Planning failed: {e}")
            context.last_error = str(e)
            context.failure_type = FailureType.UNKNOWN_FAILURE
            return StateType.RECOVERY

    async def exit(self, context: StateContext) -> None:
        pass


class VerifyActionState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.VERIFY_ACTION

    async def enter(self, context: StateContext) -> None:
        context.notify("Entering VERIFY_ACTION state: Pre-flight ROI & safety validation.", self.state_type.value)

    async def execute(self, context: StateContext) -> Optional[StateType]:
        if context.proposed_action is None or context.current_frame is None:
            context.last_error = "Missing proposed action or frame for pre-verification."
            context.failure_type = FailureType.VERIFICATION_FAILURE
            return StateType.RECOVERY

        element_id = context.proposed_action.params.get("element_id")
        if element_id:
            record = context.desktop_state_manager.coordinate_registry.resolve(
                str(element_id), context.desktop_state.screen_hash
            )
            current_window = context.desktop_state_manager.window_surface_detector.current()
            if record is None or (
                record.container_id is not None
                and (current_window is None or current_window.window_id != record.container_id)
            ):
                context.last_error = "The selected screen element is stale or its popup/window is no longer foreground."
                context.failure_type = FailureType.VERIFICATION_FAILURE
                context.notify(context.last_error, self.state_type.value)
                return StateType.RECOVERY

        # Pre-action ROI and target visibility check
        check_result = context.verifier.verify_pre_action(context.proposed_action, context.current_frame)
        context.pre_verification_result = check_result

        if not check_result.is_valid:
            context.notify(
                f"Pre-action verification failed: {check_result.reason}. Routing to RECOVERY.",
                self.state_type.value,
            )
            context.last_error = check_result.reason
            context.failure_type = FailureType.VERIFICATION_FAILURE
            return StateType.RECOVERY

        context.notify(f"Pre-action verification passed: {check_result.reason}", self.state_type.value)
        return StateType.ACT

    async def exit(self, context: StateContext) -> None:
        pass


class ActState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.ACT

    async def enter(self, context: StateContext) -> None:
        action_name = (
            context.proposed_action.action_type.value
            if context.proposed_action is not None
            else "None"
        )
        context.notify(f"Entering ACT state: Executing '{action_name}'.", self.state_type.value)

    async def execute(self, context: StateContext) -> Optional[StateType]:
        assert context.proposed_action is not None
        try:
            # Execute in thread to prevent blocking asyncio event loop
            act_result = await asyncio.to_thread(context.dispatcher.dispatch, context.proposed_action)
            context.action_result = act_result

            if not act_result.success:
                context.notify(f"Action failed at execution layer: {act_result.error}", self.state_type.value)
                context.last_error = act_result.error or "Action execution returned failure"
                context.failure_type = FailureType.ACTION_FAILURE
                return StateType.RECOVERY

            context.notify(f"Action executed successfully: {act_result.message}", self.state_type.value)
            return StateType.VERIFY_RESULT

        except Exception as e:
            logger.error(f"[ActState] Execution error: {e}")
            context.last_error = str(e)
            context.failure_type = FailureType.ACTION_FAILURE
            return StateType.RECOVERY

    async def exit(self, context: StateContext) -> None:
        pass


class VerifyResultState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.VERIFY_RESULT

    async def enter(self, context: StateContext) -> None:
        context.notify("Entering VERIFY_RESULT state: Post-action validation.", self.state_type.value)

    async def execute(self, context: StateContext) -> Optional[StateType]:
        assert context.proposed_action is not None
        assert context.action_result is not None

        # Capture post-action frame to check effect
        after_frame = await asyncio.to_thread(context.capture.capture_frame)

        post_check = context.verifier.verify_post_action(
            command=context.proposed_action,
            result=context.action_result,
            before_frame=context.before_frame,
            after_frame=after_frame,
            after_screen_text=context.screen_text,
        )

        context.post_verification_result = post_check

        if not post_check.is_valid and context.proposed_action.action_type not in (ActionType.WAIT, ActionType.READ_FILE):
            context.notify(f"Post-action verification warning: {post_check.reason}", self.state_type.value)
            context.last_error = post_check.reason
            context.failure_type = FailureType.VERIFICATION_FAILURE
            return StateType.RECOVERY

        context.notify(f"Post-action verification passed: {post_check.reason}", self.state_type.value)
        return StateType.REMEMBER

    async def exit(self, context: StateContext) -> None:
        pass


class RememberState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.REMEMBER

    async def enter(self, context: StateContext) -> None:
        context.notify("Entering REMEMBER state: Persisting action & updating working memory.", self.state_type.value)

    async def execute(self, context: StateContext) -> Optional[StateType]:
        assert context.proposed_action is not None
        assert context.action_result is not None

        # Record action in SQLite
        context.memory.record_action(
            action_type=context.proposed_action.action_type.value,
            params=context.proposed_action.params,
            status="success" if context.action_result.success else "failure",
            result_message=context.action_result.message or str(context.action_result.error or ""),
            goal_id=context.goal_id,
        )

        # Reset consecutive failure counter on success
        context.consecutive_failures = 0

        # Advance planner step
        if context.planner:
            has_more = context.planner.advance_step()
            if not has_more:
                context.is_goal_complete = True
                if context.goal_id:
                    context.memory.complete_goal(context.goal_id)
                context.notify(f"Goal '{context.goal}' completed successfully!", self.state_type.value)
                return StateType.IDLE
            else:
                context.current_task = context.planner.get_current_task()

        context.step_index += 1
        return StateType.OBSERVE

    async def exit(self, context: StateContext) -> None:
        pass


class RecoveryState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.RECOVERY

    async def enter(self, context: StateContext) -> None:
        context.notify(
            f"Entering RECOVERY state. Failure: {context.failure_type.value if context.failure_type else 'Unknown'}",
            self.state_type.value,
        )

    async def execute(self, context: StateContext) -> Optional[StateType]:
        context.consecutive_failures += 1

        if context.consecutive_failures > context.max_consecutive_failures:
            context.notify(
                f"Exceeded max consecutive failures ({context.consecutive_failures}). Escalating to ERROR.",
                self.state_type.value,
            )
            return StateType.ERROR

        # Query Recovery Planner
        f_type = context.failure_type or FailureType.UNKNOWN_FAILURE
        diagnosis = context.recovery_planner.diagnose_and_plan(
            failure_type=f_type,
            error_message=context.last_error or "Unknown failure",
            current_goal=context.goal,
            failed_command=context.proposed_action,
            step_identifier=f"step_{context.step_index}",
        )
        context.active_recovery_diagnosis = diagnosis
        context.notify(f"Recovery Strategy: {diagnosis.recommended_strategy}", self.state_type.value)

        # Execute remedial action sequence
        for remedial_cmd in diagnosis.remedial_actions:
            context.notify(f"Executing remedial action: {remedial_cmd.action_type.value}", self.state_type.value)
            await asyncio.to_thread(context.dispatcher.dispatch, remedial_cmd)
            await asyncio.sleep(0.5)

        # Reset temporary error state and re-observe
        context.last_error = None
        context.failure_type = None
        return StateType.OBSERVE

    async def exit(self, context: StateContext) -> None:
        pass


class ErrorState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.ERROR

    async def enter(self, context: StateContext) -> None:
        context.notify(f"Entering ERROR state. Fatal error: {context.last_error}", self.state_type.value)

    async def execute(self, context: StateContext) -> Optional[StateType]:
        # Formulate permanent lesson via Teacher AI
        if context.teacher and context.proposed_action:
            try:
                await context.teacher.analyze_failure(
                    failed_action=context.proposed_action.model_dump(),
                    goal=context.goal,
                    screen_context=context.screen_text,
                )
            except Exception as e:
                logger.error(f"[ErrorState] Teacher AI analysis error: {e}")

        context.notify("Fatal error handled and logged. Halting execution.", self.state_type.value)
        return StateType.SHUTDOWN

    async def exit(self, context: StateContext) -> None:
        pass


class ShutdownState(BaseState):
    @property
    def state_type(self) -> StateType:
        return StateType.SHUTDOWN

    async def enter(self, context: StateContext) -> None:
        context.notify("Entering SHUTDOWN state: Releasing handles and saving snapshot.", self.state_type.value)

    async def execute(self, context: StateContext) -> Optional[StateType]:
        try:
            context.capture.stop_capture()
            context.memory.save_agent_state(
                current_state=self.state_type.value,
                goal_id=context.goal_id,
                step_index=context.step_index,
                context_data=context.to_persisted_dict(),
            )
            context.notify("Shutdown completed cleanly.", self.state_type.value)
        except Exception as e:
            logger.error(f"[ShutdownState] Teardown error: {e}")

        # Terminal state: returns None to end state machine
        return None

    async def exit(self, context: StateContext) -> None:
        pass

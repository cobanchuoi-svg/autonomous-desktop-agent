"""
StateContext holding operational data, subsystem references, and perceptual buffers.
"""

from typing import Any, Callable, Dict, List, Optional
from PIL import Image

from agent.config import AppConfig, settings
from agent.memory.memory_manager import MemoryManager
from agent.memory.retrieval import MemoryRetrievalEngine
from agent.vision.capture import ScreenCapture
from agent.vision.base import BaseOCRProcessor
from agent.vision.factory import create_ocr_processor
from agent.brain.brain_client import BrainClient, QwenClient
from agent.brain.planner import Planner
from agent.brain.recovery_planner import RecoveryPlanner, FailureType, RecoveryDiagnosis
from agent.brain.teacher import TeacherAI
from agent.verifier.action_verifier import ActionVerifier
from agent.verifier.roi_checker import ROICheckResult
from agent.verifier.state_validator import StateValidationResult
from agent.actions.base import ActionCommand, ActionResult
from agent.actions.dispatcher import ActionDispatcher
from agent.core.benchmark import Benchmark
from agent.models.desktop_state import DesktopState, DesktopStateManager
from agent.actions.ui_automation import WindowsUIAutomationController


class StateContext:
    """Carries shared contextual data across FSM state executions."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        memory: Optional[MemoryManager] = None,
        capture: Optional[ScreenCapture] = None,
        ocr: Optional[BaseOCRProcessor] = None,
        brain: Optional[BrainClient] = None,
        qwen: Optional[BrainClient] = None,
        dispatcher: Optional[ActionDispatcher] = None,
        verifier: Optional[ActionVerifier] = None,
        recovery_planner: Optional[RecoveryPlanner] = None,
        teacher: Optional[TeacherAI] = None,
    ):
        self.config: AppConfig = config or settings
        self.memory: MemoryManager = memory or MemoryManager()
        self.retrieval: MemoryRetrievalEngine = MemoryRetrievalEngine(self.memory)
        self.capture: ScreenCapture = capture or ScreenCapture()
        self.ocr: BaseOCRProcessor = ocr or create_ocr_processor(self.config.ocr_engine)
        self.dispatcher: ActionDispatcher = dispatcher or ActionDispatcher()
        self.verifier: ActionVerifier = verifier or ActionVerifier()
        self.recovery_planner: RecoveryPlanner = recovery_planner or RecoveryPlanner()

        # Brain components
        self.brain: Optional[BrainClient] = brain or qwen
        self.planner: Optional[Planner] = None
        self.teacher: Optional[TeacherAI] = teacher

        # Ephemeral Goal & Task context
        self.goal: str = ""
        self.goal_id: Optional[int] = None
        self.step_index: int = 0
        self.current_task: Optional[str] = None
        self.is_goal_complete: bool = False
        self.should_shutdown: bool = False

        # Visual frames
        self.current_frame: Optional[Image.Image] = None
        self.before_frame: Optional[Image.Image] = None
        self.ocr_result: Optional[Dict[str, Any]] = None
        self.screen_text: str = ""
        self.desktop_state_manager = DesktopStateManager()
        self.desktop_state: DesktopState = self.desktop_state_manager.current
        self.ui_automation = WindowsUIAutomationController()
        self.benchmark = Benchmark()

        # Cognitive & verification artifacts
        self.retrieved_memories: List[str] = []
        self.proposed_action: Optional[ActionCommand] = None
        self.pre_verification_result: Optional[ROICheckResult] = None
        self.action_result: Optional[ActionResult] = None
        self.post_verification_result: Optional[StateValidationResult] = None

        # Failure / Recovery telemetry
        self.last_error: Optional[str] = None
        self.failure_type: Optional[FailureType] = None
        self.active_recovery_diagnosis: Optional[RecoveryDiagnosis] = None
        self.consecutive_failures: int = 0
        self.max_consecutive_failures: int = 3

        # UI/Log listeners: cb(message, state_name)
        self.listeners: List[Callable[[str, str], None]] = []

    def notify(self, message: str, state_name: str) -> None:
        """Broadcast state event to UI/CLI listeners."""
        for listener in self.listeners:
            try:
                listener(message, state_name)
            except Exception:
                pass

    def to_persisted_dict(self) -> Dict[str, Any]:
        """Convert critical recovery state into JSON-serializable dictionary."""
        return {
            "goal": self.goal,
            "goal_id": self.goal_id,
            "step_index": self.step_index,
            "current_task": self.current_task,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "failure_type": self.failure_type.value if self.failure_type else None,
        }

    @property
    def qwen(self) -> Optional[BrainClient]:
        """Backward-compatibility alias for self.brain."""
        return self.brain

    @qwen.setter
    def qwen(self, value: Optional[BrainClient]) -> None:
        self.brain = value

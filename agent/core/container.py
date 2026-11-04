"""
Dependency Injection Container.
Wires domain interfaces to concrete implementations cleanly adhering to Clean Architecture.
"""

from typing import Optional
from agent.config import AppConfig, settings
from agent.vision.base import BaseScreenCapture, BaseOCRProcessor
from agent.vision.capture import ScreenCapture
from agent.vision.factory import create_ocr_processor
from agent.memory.base import BaseMemoryManager
from agent.memory.db import DatabaseManager
from agent.memory.memory_manager import MemoryManager
from agent.llm.base import BaseLLMProvider
from agent.llm.factory import create_llm_provider
from agent.brain.brain_client import BrainClient
from agent.actions.base import BaseActionDispatcher
from agent.actions import ActionDispatcher
from agent.actions.safety import SafetyGuard
from agent.verifier.action_verifier import ActionVerifier
from agent.brain.recovery_planner import RecoveryPlanner
from agent.plugins.manager import PluginManager
from agent.plugins.browser_plugin import BrowserPlugin
from agent.plugins.vscode_plugin import VSCodePlugin
from agent.plugins.explorer_plugin import ExplorerPlugin
from agent.core.engine import AgentEngine
from agent.logger import logger


class Container:
    """Dependency Injection Container managing lifecycles and component resolution."""

    def __init__(self, config: Optional[AppConfig] = None):
        self.config: AppConfig = config or settings

        # Singletons / managed instances
        self._db: Optional[DatabaseManager] = None
        self._memory: Optional[BaseMemoryManager] = None
        self._capture: Optional[BaseScreenCapture] = None
        self._ocr: Optional[BaseOCRProcessor] = None
        self._llm: Optional[BaseLLMProvider] = None
        self._brain: Optional[BrainClient] = None
        self._safety: Optional[SafetyGuard] = None
        self._dispatcher: Optional[BaseActionDispatcher] = None
        self._plugin_manager: Optional[PluginManager] = None
        self._engine: Optional[AgentEngine] = None

    @property
    def db(self) -> DatabaseManager:
        if self._db is None:
            self._db = DatabaseManager(self.config.db_path)
        return self._db

    @property
    def memory(self) -> BaseMemoryManager:
        if self._memory is None:
            self._memory = MemoryManager(self.db)
        return self._memory

    def set_memory(self, memory: BaseMemoryManager) -> None:
        self._memory = memory

    @property
    def capture(self) -> BaseScreenCapture:
        if self._capture is None:
            self._capture = ScreenCapture()
        return self._capture

    def set_capture(self, capture: BaseScreenCapture) -> None:
        self._capture = capture

    @property
    def ocr(self) -> BaseOCRProcessor:
        if self._ocr is None:
            self._ocr = create_ocr_processor(self.config.ocr_engine)
        return self._ocr

    def set_ocr(self, ocr: BaseOCRProcessor) -> None:
        self._ocr = ocr

    @property
    def safety(self) -> SafetyGuard:
        if self._safety is None:
            self._safety = SafetyGuard(self.config.safety)
        return self._safety

    @property
    def dispatcher(self) -> BaseActionDispatcher:
        if self._dispatcher is None:
            self._dispatcher = ActionDispatcher(safety_guard=self.safety)
        return self._dispatcher

    def set_dispatcher(self, dispatcher: BaseActionDispatcher) -> None:
        self._dispatcher = dispatcher

    @property
    def plugin_manager(self) -> PluginManager:
        if self._plugin_manager is None:
            pm = PluginManager()
            pm.register_plugin(BrowserPlugin())
            pm.register_plugin(VSCodePlugin())
            pm.register_plugin(ExplorerPlugin())
            self._plugin_manager = pm
        return self._plugin_manager

    async def get_llm(self) -> BaseLLMProvider:
        if self._llm is None:
            self._llm = await create_llm_provider(self.config.llm)
        return self._llm

    def set_llm(self, llm: BaseLLMProvider) -> None:
        self._llm = llm
        self._brain = BrainClient(llm)

    async def get_brain(self) -> BrainClient:
        if self._brain is None:
            llm = await self.get_llm()
            self._brain = BrainClient(llm)
        return self._brain

    async def create_engine(self) -> AgentEngine:
        """Construct the engine; defer LLM startup until an unknown goal needs it."""
        engine = AgentEngine(
            config=self.config,
            brain_client=self._brain,
            memory_manager=self.memory,  # type: ignore
            screen_capture=self.capture,  # type: ignore
            ocr_processor=self.ocr,  # type: ignore
            dispatcher=self.dispatcher,  # type: ignore
            verifier=ActionVerifier(),
            recovery_planner=RecoveryPlanner(),
        )
        return engine


# Global DI container instance
container = Container()

"""
Abstract Plugin interface and metadata models.
Conforms strictly to TDD Section 17.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PluginMetadata(BaseModel):
    name: str
    version: str = "1.0.0"
    description: str
    author: str = "Desktop AI Agent"
    supported_actions: List[str] = Field(default_factory=list)


class BasePlugin(ABC):
    """Abstract interface that all plugins must implement."""

    def __init__(self, metadata: PluginMetadata):
        self.metadata = metadata
        self._is_initialized = False

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize plugin resources, external drivers, or connections."""
        pass

    @abstractmethod
    def execute(self, action_name: str, **kwargs: Any) -> Any:
        """Execute a specialized plugin action."""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Release allocated handles and safely shut down."""
        pass

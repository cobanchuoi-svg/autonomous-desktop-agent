"""
Abstract base class and models for the local LLM abstraction layer.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, Optional
from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """Structured response from an LLM inference call."""
    content: str
    thought: Optional[str] = None
    reason: Optional[str] = None
    action: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    raw_response: Optional[str] = None


class BaseLLMProvider(ABC):
    """Abstract interface that all LLM backends must implement."""

    def __init__(self, model_name: str, temperature: float = 0.2, max_tokens: int = 1024):
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. ollama, llamacpp, transformers)."""
        pass

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        """Generate raw text or JSON string from prompt."""
        pass

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """Stream generated text when supported; default to one complete chunk."""
        yield await self.generate(prompt, system_prompt=system_prompt, json_mode=json_mode)

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if backend service or model weights are loaded and ready."""
        pass

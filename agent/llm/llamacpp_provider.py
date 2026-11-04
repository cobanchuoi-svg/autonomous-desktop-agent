"""
llama-cpp-python LLM Provider fallback implementation.
"""

import asyncio
from typing import Optional
from agent.llm.base import BaseLLMProvider
from agent.core.exceptions import LLMInferenceException
from agent.logger import logger

try:
    from llama_cpp import Llama
    LLAMA_CPP_AVAILABLE = True
except ImportError:
    LLAMA_CPP_AVAILABLE = False
    Llama = None


class LlamaCppProvider(BaseLLMProvider):
    """Fallback LLM backend executing GGUF models directly via llama-cpp-python."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        model_name: str = "qwen2-2b-instruct.Q4_K_M.gguf",
        temperature: float = 0.2,
        max_tokens: int = 1024,
        n_ctx: int = 2048,
    ):
        super().__init__(model_name=model_name, temperature=temperature, max_tokens=max_tokens)
        self.model_path = model_path
        self.n_ctx = n_ctx
        self._llm: Optional[Llama] = None

    @property
    def provider_name(self) -> str:
        return "llamacpp"

    async def health_check(self) -> bool:
        if not LLAMA_CPP_AVAILABLE:
            return False
        if not self.model_path:
            return False
        try:
            return await asyncio.to_thread(self._ensure_loaded)
        except Exception:
            return False

    def _ensure_loaded(self) -> bool:
        if self._llm is None:
            if not self.model_path or not LLAMA_CPP_AVAILABLE:
                return False
            self._llm = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                verbose=False,
            )
        return True

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        if not LLAMA_CPP_AVAILABLE:
            raise LLMInferenceException("llama-cpp-python is not installed.")

        if not self._ensure_loaded():
            raise LLMInferenceException(f"Failed to load llama-cpp model from {self.model_path}")

        full_prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n" if system_prompt else prompt

        def _infer():
            assert self._llm is not None
            output = self._llm(
                full_prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stop=["<|im_end|>", "\n\n\n"],
            )
            return output["choices"][0]["text"]

        return await asyncio.to_thread(_infer)

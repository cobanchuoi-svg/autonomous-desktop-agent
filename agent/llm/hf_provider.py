"""
Hugging Face Transformers LLM Provider fallback implementation.
"""

import asyncio
from typing import Optional
from agent.llm.base import BaseLLMProvider
from agent.core.exceptions import LLMInferenceException
from agent.logger import logger

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False


class HuggingFaceProvider(BaseLLMProvider):
    """Fallback LLM backend executing models via PyTorch and HuggingFace transformers."""

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2-1.5B-Instruct",
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ):
        super().__init__(model_name=model_name, temperature=temperature, max_tokens=max_tokens)
        self._tokenizer = None
        self._model = None

    @property
    def provider_name(self) -> str:
        return "transformers"

    async def health_check(self) -> bool:
        return TRANSFORMERS_AVAILABLE

    def _ensure_loaded(self):
        if self._model is None and TRANSFORMERS_AVAILABLE:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                device_map=device,
            )

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        if not TRANSFORMERS_AVAILABLE:
            raise LLMInferenceException("HuggingFace transformers or torch is not installed.")

        def _infer():
            self._ensure_loaded()
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            text = self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
            model_inputs = self._tokenizer([text], return_tensors="pt").to(self._model.device)

            generated_ids = self._model.generate(
                **model_inputs,
                max_new_tokens=self.max_tokens,
                temperature=self.temperature,
                do_sample=self.temperature > 0.0,
            )
            generated_ids = [
                output_ids[len(input_ids):]
                for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
            ]
            return self._tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]

        return await asyncio.to_thread(_infer)

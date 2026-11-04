"""
Ollama LLM Provider implementation using async httpx.
"""

import json
from typing import AsyncIterator, Optional
import httpx
from agent.llm.base import BaseLLMProvider
from agent.core.exceptions import LLMInferenceException
from agent.logger import logger


class OllamaProvider(BaseLLMProvider):
    """Preferred local LLM backend connecting to Ollama daemon (e.g. Qwen 2B)."""

    def __init__(
        self,
        model_name: str = "qwen2.5:3b",
        base_url: str = "http://127.0.0.1:11434",
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ):
        super().__init__(model_name=model_name, temperature=temperature, max_tokens=max_tokens)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def health_check(self) -> bool:
        """Verify Ollama daemon is reachable and responding."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                return res.status_code == 200
        except Exception as e:
            logger.debug(f"[Ollama] Health check failed: {e}")
            return False

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        """Call Ollama /api/generate or /api/chat with streaming disabled."""
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        if system_prompt:
            payload["system"] = system_prompt

        if json_mode:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                if response.status_code != 200:
                    raise LLMInferenceException(
                        f"Ollama returned HTTP {response.status_code}: {response.text}"
                    )
                data = response.json()
                return data.get("response", "")
        except httpx.RequestError as exc:
            raise LLMInferenceException(f"Failed to communicate with Ollama: {exc}") from exc

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """Yield response fragments from Ollama's newline-delimited stream."""
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt
        if json_mode:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/api/generate", json=payload
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise LLMInferenceException(
                            f"Ollama returned HTTP {response.status_code}: {body}"
                        )
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise LLMInferenceException(
                                f"Ollama returned an invalid stream chunk: {line[:160]}"
                            ) from exc
                        if item.get("error"):
                            raise LLMInferenceException(str(item["error"]))
                        fragment = item.get("response", "")
                        if fragment:
                            yield fragment
                        if item.get("done"):
                            break
        except httpx.RequestError as exc:
            raise LLMInferenceException(f"Failed to communicate with Ollama: {exc}") from exc

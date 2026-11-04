"""
Gemini LLM Provider implementation using async httpx directly (no extra bloated SDK required).
Supports standard generation, structured JSON mode, and streaming.
"""

import json
from typing import Any, AsyncIterator, Dict, Optional
import httpx

from agent.core.exceptions import LLMInferenceException
from agent.llm.base import BaseLLMProvider
from agent.logger import logger


class GeminiProvider(BaseLLMProvider):
    """Cloud LLM backend connecting to Google Gemini API (e.g. gemini-1.5-flash / gemini-2.0-flash)."""

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-3.8-flash",
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ):
        super().__init__(model_name=model_name, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _get_headers_and_url(self, endpoint: str) -> tuple[str, dict]:
        """Support both standard API keys (including new AI Studio AQ.* / AIza* formats) and OAuth Bearer tokens."""
        headers = {"Content-Type": "application/json"}
        if self.api_key.startswith("Bearer ") or self.api_key.startswith("ya29."):
            token = self.api_key.removeprefix("Bearer ").strip()
            headers["Authorization"] = f"Bearer {token}"
            url = f"{self.base_url}/{self.model_name}:{endpoint}"
        else:
            headers["x-goog-api-key"] = self.api_key
            url = f"{self.base_url}/{self.model_name}:{endpoint}?key={self.api_key}"
        return url, headers

    async def health_check(self) -> bool:
        """Verify API key is valid by sending a minimal generate request.
        Auto-recovers if Google deprecates the configured model or experiences temporary high-demand spikes (503/429).
        """
        import re
        if not self.api_key:
            logger.warning("[Gemini] API key is empty.")
            return False
        try:
            url, headers = self._get_headers_and_url("generateContent")
            payload = {
                "contents": [{"parts": [{"text": "hi"}]}],
                "generationConfig": {"maxOutputTokens": 1},
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    logger.info(f"[Gemini] Health check OK (model={self.model_name})")
                    return True

                # Handle Google model deprecation (HTTP 404 advising newer model)
                if res.status_code == 404:
                    suggested = re.findall(r"models/(gemini-[\w\.-]+)", res.text)
                    candidates = [m for m in suggested if m != self.model_name]
                    candidates.extend(["gemini-3.8-flash", "gemini-flash-latest", "gemini-pro-latest", "gemini-2.5-flash-lite"])
                    for candidate in candidates:
                        logger.info(f"[Gemini] Model '{self.model_name}' 404; trying candidate '{candidate}'...")
                        self.model_name = candidate
                        url, headers = self._get_headers_and_url("generateContent")
                        retry_res = await client.post(url, headers=headers, json=payload)
                        if retry_res.status_code == 200:
                            logger.info(f"[Gemini] Health check recovered! Using active model: {self.model_name}")
                            return True
                        if retry_res.status_code in {503, 429}:
                            logger.info(f"[Gemini] Health check verified credentials via model '{self.model_name}' (HTTP {retry_res.status_code})")
                            return True

                # HTTP 503 (High demand) or 429 (Rate limit) explicitly confirms the API key is VALID and recognized
                if res.status_code in {503, 429}:
                    logger.info(f"[Gemini] Credentials verified! Server returned HTTP {res.status_code} (traffic spike, will retry automatically during chat).")
                    return True

                logger.warning(f"[Gemini] Health check HTTP {res.status_code}: {res.text[:200]}")
                return False
        except Exception as e:
            logger.debug(f"[Gemini] Health check failed: {e}")
            return False

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        """Call Gemini generateContent endpoint."""
        url, headers = self._get_headers_and_url("generateContent")

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            }
        }

        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for attempt in range(3):
                    response = await client.post(url, headers=headers, json=payload)
                    if response.status_code == 200:
                        break
                    if response.status_code in {503, 429} and attempt < 2:
                        logger.warning(f"[Gemini] Got HTTP {response.status_code} ({self.model_name}); retrying in 1s (attempt {attempt + 1}/3)...")
                        await asyncio.sleep(1.0)
                        continue
                    raise LLMInferenceException(
                        f"Gemini API returned HTTP {response.status_code}: {response.text}"
                    )
                data = response.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return ""
                parts = candidates[0].get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts)
        except httpx.RequestError as exc:
            raise LLMInferenceException(f"Failed to communicate with Gemini API: {exc}") from exc

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """Call Gemini streamGenerateContent endpoint using SSE."""
        url, headers = self._get_headers_and_url("streamGenerateContent")
        if "?" in url:
            url += "&alt=sse"
        else:
            url += "?alt=sse"

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            }
        }

        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        raise LLMInferenceException(
                            f"Gemini API stream returned HTTP {response.status_code}"
                        )
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str:
                                try:
                                    chunk = json.loads(data_str)
                                    parts = chunk.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                                    text = "".join(p.get("text", "") for p in parts)
                                    if text:
                                        yield text
                                except Exception:
                                    continue
        except httpx.RequestError as exc:
            raise LLMInferenceException(f"Gemini streaming connection failed: {exc}") from exc

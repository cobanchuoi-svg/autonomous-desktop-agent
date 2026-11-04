"""
GeminiCLIProvider — calls the local `gemini` CLI (already authenticated via Antigravity/Google)
as a full LLM provider.  No REST API key required.

Usage in config.json:
  "provider": "gemini_cli"
  "model_name": "gemini-2.0-flash"   (or "flash", "flash-lite", etc.)
"""

import asyncio
import json
import re
import shutil
import subprocess
from typing import Any, AsyncIterator, Optional

from agent.core.exceptions import LLMInferenceException
from agent.llm.base import BaseLLMProvider
from agent.logger import logger

_ANSI_STRIP = re.compile(r"\x1b\[[0-9;]*[mGKHF]")


def _strip_ansi(text: str) -> str:
    return _ANSI_STRIP.sub("", text)


class GeminiCLIProvider(BaseLLMProvider):
    """
    LLM provider that shells out to the locally-installed `gemini` CLI.
    The CLI is already authenticated via the Antigravity / Google account,
    so no separate API key is needed.
    """

    def __init__(
        self,
        model_name: str = "gemini-2.0-flash",
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout: float = 60.0,
        command: str = "gemini",
    ):
        super().__init__(model_name=model_name, temperature=temperature, max_tokens=max_tokens)
        self.timeout = max(10.0, float(timeout))
        self.command = command
        self._executable: Optional[str] = None

    @property
    def provider_name(self) -> str:
        return "gemini_cli"

    def _find_executable(self) -> Optional[str]:
        if self._executable:
            return self._executable
        import os
        exe = shutil.which(self.command)
        if exe:
            # On Windows, prefer native .ps1 over .cmd/.bat to bypass CMD.exe batch argument parser quirks
            if os.name == "nt":
                ps1 = os.path.splitext(exe)[0] + ".ps1"
                if os.path.exists(ps1):
                    exe = ps1
            self._executable = exe
        return exe

    async def health_check(self) -> bool:
        exe = self._find_executable()
        if not exe:
            logger.warning(f"[GeminiCLI] '{self.command}' not found on PATH.")
            return False
        try:
            result = await asyncio.to_thread(
                self._run_cli, "Reply with the single word: OK", timeout=35.0
            )
            if result and len(result.strip()) < 200:
                logger.info(f"[GeminiCLI] Health check OK → '{result.strip()[:60]}'")
                return True
            logger.warning(f"[GeminiCLI] Health check unexpected response: {result[:100]!r}")
            return False
        except Exception as exc:
            logger.warning(f"[GeminiCLI] Health check error: {exc}")
            return False

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        full_prompt = self._build_prompt(prompt, system_prompt, json_mode)
        try:
            raw = await asyncio.to_thread(self._run_cli, full_prompt, self.timeout)
        except subprocess.TimeoutExpired:
            raise LLMInferenceException("Gemini CLI timed out.")
        except Exception as exc:
            raise LLMInferenceException(f"Gemini CLI error: {exc}") from exc
        return self._postprocess(raw, json_mode)

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        # CLI doesn't support real streaming — yield the full response as one chunk
        result = await self.generate(prompt, system_prompt=system_prompt, json_mode=json_mode)
        if result:
            yield result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(prompt: str, system_prompt: Optional[str], json_mode: bool) -> str:
        parts = []
        if system_prompt:
            parts.append(system_prompt)
        parts.append(prompt)
        if json_mode:
            parts.append(
                "\n\nIMPORTANT: Output a single valid JSON object only. "
                "No markdown fences, no prose before or after."
            )
        return "\n\n".join(parts)

    def _run_cli(self, prompt: str, timeout: float = 60.0) -> str:
        """Run gemini CLI synchronously (called via asyncio.to_thread).

        On Windows, the prompt is passed via a base64-encoded PowerShell script to
        prevent CMD.exe from interpreting shell metacharacters (|, &, >, etc.) that
        appear inside the prompt string.
        """
        import base64
        import os
        import tempfile

        exe = self._find_executable()
        if not exe:
            raise FileNotFoundError(f"'{self.command}' CLI not found on PATH.")

        model_flag = self._normalize_model(self.model_name)
        logger.debug(f"[GeminiCLI] Running: {exe} --model {model_flag} (prompt len={len(prompt)})")

        if os.name == "nt":
            # --- Windows: wrap in PowerShell to avoid CMD metacharacter issues ---
            exe_b64 = base64.b64encode(exe.encode("utf-8")).decode("ascii")
            prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
            model_b64 = base64.b64encode(model_flag.encode("utf-8")).decode("ascii")

            ps_script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$env:FORCE_COLOR = '0'
$env:NO_COLOR = '1'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$cli    = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{exe_b64}'))
$prompt = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{prompt_b64}'))
$model  = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{model_b64}'))
# Note: --yolo flag lets the Gemini CLI auto-approve its own tool calls
$result = & $cli --prompt $prompt --model $model --yolo --skip-trust
$exitCode = $LASTEXITCODE
[Console]::Out.Write(($result -join [Environment]::NewLine))
if ($exitCode -ne 0) {{ exit $exitCode }}
"""
            encoded_cmd = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
            cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_cmd]
            cwd = None
        else:
            # --- Unix: pass directly, shell=False is safe ---
            # Note: --yolo flag lets the Gemini CLI auto-approve its own tool calls
            cmd = [exe, "--prompt", prompt, "--model", model_flag, "--yolo"]
            cwd = None

        completed = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

        stdout = _strip_ansi(completed.stdout or "").strip()
        stderr = _strip_ansi(completed.stderr or "").strip()

        # If stdout contains model response, return it immediately (ignore non-fatal warnings in stderr)
        if stdout:
            return stdout

        if completed.returncode != 0:
            # Strip harmless CLIXML wrapper and Node.js warnings from error message
            clean_err = "\n".join(
                line for line in (stderr or stdout).splitlines()
                if "Warning:" not in line and "CLIXML" not in line and not line.startswith("<")
            ).strip() or stderr or stdout or "Gemini CLI returned non-zero exit code."
            raise LLMInferenceException(f"Gemini CLI exit {completed.returncode}: {clean_err[:500]}")

        # Some CLI builds write to stderr even on success
        return stdout or stderr

    @staticmethod
    def _normalize_model(model_name: str) -> str:
        """Map full model names to CLI aliases if needed."""
        mapping = {
            "gemini-2.0-flash": "gemini-2.0-flash",
            "gemini-1.5-flash": "gemini-1.5-flash",
            "gemini-2.5-flash": "gemini-2.5-flash",
            "gemini-2.0-flash-lite": "gemini-2.0-flash-lite",
        }
        return mapping.get(model_name, model_name)

    @staticmethod
    def _postprocess(raw: str, json_mode: bool) -> str:
        """Strip markdown fences and leading/trailing whitespace."""
        text = raw.strip()
        if text.startswith("```"):
            # Remove opening fence (```json or ```)
            text = text.split("\n", 1)[-1]
            # Remove closing fence
            if "```" in text:
                text = text.rsplit("```", 1)[0]
            text = text.strip()
        if json_mode:
            # Find the JSON object in case there's prose around it
            start = text.find("{")
            end = text.rfind("}")
            if 0 <= start < end:
                text = text[start:end + 1]
        return text

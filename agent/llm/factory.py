"""
LLM Provider Factory with automatic cascading fallback:
1. Gemini REST API (cloud, requires gemini_api_key or GEMINI_API_KEY env var)
2. Gemini CLI (cloud via local gemini CLI, explicit opt-in only)
3. Ollama (local)
4. llama-cpp-python (fallback)
5. HuggingFace Transformers (fallback)
6. Mock (dry-run / testing)
"""

from typing import Optional
from agent.config import LLMConfig
from agent.llm.base import BaseLLMProvider
from agent.llm.gemini_provider import GeminiProvider
from agent.llm.gemini_cli_provider import GeminiCLIProvider
from agent.llm.ollama_provider import OllamaProvider
from agent.llm.llamacpp_provider import LlamaCppProvider
from agent.llm.hf_provider import HuggingFaceProvider
from agent.llm.mock_provider import MockLLMProvider
from agent.logger import logger


async def create_llm_provider(
    config: Optional[LLMConfig] = None,
    preferred_provider: Optional[str] = None,
    allow_mock_fallback: bool = True,
) -> BaseLLMProvider:
    """Instantiate and verify the LLM provider following the fallback hierarchy."""
    if config is None:
        from agent.config import settings
        config = settings.llm

    target_provider = (preferred_provider or config.provider).lower()

    # 1. Cloud: Gemini REST API (requires API key)
    if target_provider == "gemini":
        api_key = getattr(config, "gemini_api_key", None) or ""
        if api_key:
            model = config.model_name or "gemini-3.8-flash"
            if model in {"gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"}:
                model = "gemini-3.8-flash"
            provider = GeminiProvider(
                api_key=api_key,
                model_name=model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=config.request_timeout,
            )
            if await provider.health_check():
                logger.info(f"[LLM Factory] Selected Gemini REST provider with model '{provider.model_name}'")
                return provider
            logger.warning("[LLM Factory] Gemini REST health check failed. Falling back to local Ollama...")
        else:
            logger.warning(
                "[LLM Factory] No Gemini API key found. Please set GEMINI_API_KEY environment variable "
                "or configure config.local.json. Falling back to local Ollama..."
            )
        # Bug fix: redirect target_provider to ollama so the local chain executes
        target_provider = "ollama"

    # 1b. Explicitly select Gemini CLI (opt-in only, no API key needed)
    if target_provider == "gemini_cli":
        cli_provider = GeminiCLIProvider(
            model_name=config.model_name if "gemini" in config.model_name else "gemini-2.0-flash",
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=getattr(config, "gemini_cli_timeout", 60.0),
        )
        if await cli_provider.health_check():
            logger.info(f"[LLM Factory] Selected Gemini CLI provider (model={cli_provider.model_name})")
            return cli_provider
        logger.warning("[LLM Factory] Gemini CLI not available. Falling back to local Ollama...")
        target_provider = "ollama"

    # 2. Preferred Local: Ollama (uses ollama_model, not model_name)
    if target_provider == "ollama":
        ollama_model = getattr(config, "ollama_model", "qwen2.5:3b") or "qwen2.5:3b"
        provider = OllamaProvider(
            model_name=ollama_model,
            base_url=config.ollama_base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.request_timeout,
        )
        if await provider.health_check():
            logger.info(f"[LLM Factory] Selected Ollama provider with model '{ollama_model}'")
            return provider
        logger.warning("[LLM Factory] Ollama service not reachable. Attempting fallback...")

    # 3. Fallback: llama-cpp-python
    if target_provider in ("ollama", "llamacpp"):
        llamacpp = LlamaCppProvider(
            model_path=config.llamacpp_model_path,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        if await llamacpp.health_check():
            logger.info("[LLM Factory] Selected llama-cpp-python fallback provider")
            return llamacpp
        if target_provider == "llamacpp":
            logger.warning("[LLM Factory] llama-cpp-python fallback unavailable. Trying next fallback...")

    # 4. Fallback: HuggingFace Transformers
    if target_provider in ("ollama", "llamacpp", "transformers"):
        hf_provider = HuggingFaceProvider(
            model_name=config.hf_model_id,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        if await hf_provider.health_check():
            logger.info(f"[LLM Factory] Selected HuggingFace Transformers fallback provider '{config.hf_model_id}'")
            return hf_provider
        logger.warning("[LLM Factory] HuggingFace Transformers fallback unavailable.")

    # 5. Fallback: Mock provider for testing/dry-run
    if allow_mock_fallback or target_provider == "mock":
        logger.warning(
            "[LLM Factory] Falling back to MockLLMProvider. WARNING: All answers and responses are FAKE / SIMULATED! "
            "To get real responses, supply a Gemini API key via the GEMINI_API_KEY environment variable or config.local.json, "
            "or start a local Ollama instance (ollama serve)."
        )
        return MockLLMProvider()

    raise RuntimeError("No suitable LLM backend available.")

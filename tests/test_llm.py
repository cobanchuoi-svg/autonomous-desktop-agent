"""
Unit tests for LLM Abstraction Layer and Brain Client.
"""

import pytest
from agent.llm.mock_provider import MockLLMProvider
from agent.llm.factory import create_llm_provider
from agent.brain.brain_client import BrainClient, QwenClient


@pytest.mark.asyncio
async def test_llm_provider_abstraction():
    provider = MockLLMProvider()
    assert provider.provider_name == "mock"
    assert await provider.health_check() is True

    raw = await provider.generate(prompt="Goal: open chrome")
    assert "chrome" in raw.lower()


@pytest.mark.asyncio
async def test_brain_client_structured_action():
    provider = MockLLMProvider()
    client = BrainClient(provider)

    res = await client.generate_action(
        goal="Open Google Chrome",
        screen_text="Desktop icons: Chrome, Trash, Files",
    )
    assert res.action == "launch_app"
    assert res.params.get("app_name") == "chrome"
    assert len(res.thought) > 0


@pytest.mark.asyncio
async def test_qwen_client_backward_compatibility():
    provider = MockLLMProvider()
    client = QwenClient(provider)
    assert isinstance(client, BrainClient)
    res = await client.generate_action(
        goal="Open Google Chrome",
        screen_text="Desktop icons: Chrome, Trash, Files",
    )
    assert res.params.get("app_name") == "chrome"
    assert len(res.thought) > 0


@pytest.mark.asyncio
async def test_factory_fallback():
    # Force mock provider or check graceful fallback
    provider = await create_llm_provider(preferred_provider="mock")
    assert provider.provider_name == "mock"

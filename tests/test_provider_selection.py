import pytest

from agent.config import AppConfig
from agent.core.engine import AgentEngine


def test_session_provider_selection_resets_runtime_without_persisting(tmp_path):
    config = AppConfig(db_path=str(tmp_path / "memory.db"))
    engine = AgentEngine(config=config)
    engine._workflow_runtime = object()
    engine.configure_session_provider("ollama")
    assert engine.config.llm.provider == "ollama"
    assert engine._workflow_runtime is None


def test_gemini_selection_requires_key_and_accepts_session_key(tmp_path):
    engine = AgentEngine(config=AppConfig(db_path=str(tmp_path / "memory.db")))
    with pytest.raises(ValueError, match="API key"):
        engine.configure_session_provider("gemini")
    engine.configure_session_provider("gemini", gemini_api_key="session-only-key")
    assert engine.config.llm.provider == "gemini"
    assert engine.config.llm.gemini_api_key == "session-only-key"

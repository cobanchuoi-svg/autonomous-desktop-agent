"""
Tests for configuration management, secret handling, and precedence loading.
"""

import json
from pathlib import Path
import pytest
from agent.config import AppConfig, LLMConfig, load_config, CONFIG_FILE_PATH


def test_committed_config_has_no_api_key():
    """Verify that the committed config.json does not contain any API key or secret token."""
    assert CONFIG_FILE_PATH.exists(), "config.json must exist in repo root"
    content = CONFIG_FILE_PATH.read_text(encoding="utf-8")

    # Check for sensitive patterns without storing literal pattern strings in test file
    forbidden_prefixes = ["A" + "Q.", "A" + "Iza", "ya" + "29."]
    for prefix in forbidden_prefixes:
        assert prefix not in content, f"config.json must not contain {prefix} tokens"

    data = json.loads(content)
    llm_section = data.get("llm", {})
    # gemini_api_key should either be absent or completely empty
    assert not llm_section.get("gemini_api_key"), "llm.gemini_api_key in config.json must be empty or removed"


def test_no_key_by_default(monkeypatch, tmp_path):
    """Verify that by default without env vars or config.local.json, no API key is set."""
    monkeypatch.delenv("AGENT_LLM__GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    fake_config = tmp_path / "config.json"
    fake_config.write_text(json.dumps({
        "app_name": "Test Agent",
        "llm": {"provider": "gemini", "model_name": "gemini-2.0-flash"}
    }), encoding="utf-8")

    cfg = load_config(fake_config)
    assert not cfg.llm.gemini_api_key


def test_env_var_overrides_file(monkeypatch, tmp_path):
    """Verify that environment variables take highest precedence for gemini_api_key."""
    fake_config = tmp_path / "config.json"
    fake_config.write_text(json.dumps({
        "app_name": "Test Agent",
        "llm": {"provider": "gemini", "gemini_api_key": "file_key"}
    }), encoding="utf-8")

    # 1. Test GEMINI_API_KEY
    monkeypatch.setenv("GEMINI_API_KEY", "env_gemini_key_123")
    monkeypatch.delenv("AGENT_LLM__GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    cfg = load_config(fake_config)
    assert cfg.llm.gemini_api_key == "env_gemini_key_123"

    # 2. Test AGENT_LLM__GEMINI_API_KEY overrides GEMINI_API_KEY
    monkeypatch.setenv("AGENT_LLM__GEMINI_API_KEY", "agent_specific_key_456")
    cfg2 = load_config(fake_config)
    assert cfg2.llm.gemini_api_key == "agent_specific_key_456"

    # 3. Test GOOGLE_API_KEY as fallback env var
    monkeypatch.delenv("AGENT_LLM__GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google_api_key_789")
    cfg3 = load_config(fake_config)
    assert cfg3.llm.gemini_api_key == "google_api_key_789"


def test_config_local_json_is_merged(monkeypatch, tmp_path):
    """Verify that config.local.json is deep-merged over config.json."""
    monkeypatch.delenv("AGENT_LLM__GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    fake_config = tmp_path / "config.json"
    fake_config.write_text(json.dumps({
        "app_name": "Original Name",
        "llm": {
            "provider": "ollama",
            "model_name": "original-model",
            "temperature": 0.5
        }
    }), encoding="utf-8")

    fake_local = tmp_path / "config.local.json"
    fake_local.write_text(json.dumps({
        "llm": {
            "provider": "gemini",
            "gemini_api_key": "local_merged_key"
        }
    }), encoding="utf-8")

    cfg = load_config(fake_config)
    # Merged fields
    assert cfg.llm.provider == "gemini"
    assert cfg.llm.gemini_api_key == "local_merged_key"
    # Preserved original fields from config.json
    assert cfg.llm.model_name == "original-model"
    assert cfg.llm.temperature == 0.5
    assert cfg.app_name == "Original Name"


def test_gemini_cli_enabled_defaults_to_false(monkeypatch, tmp_path):
    """Verify that gemini_cli_enabled defaults to False in both config and dataclass/model."""
    # Check default instance
    default_cfg = AppConfig()
    assert default_cfg.gemini_cli_enabled is False

    # Check committed config file
    loaded_cfg = load_config(CONFIG_FILE_PATH)
    assert loaded_cfg.gemini_cli_enabled is False


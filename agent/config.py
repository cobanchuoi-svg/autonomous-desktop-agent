"""
Configuration management using pydantic-settings with JSON fallback.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field
    from pydantic_settings import BaseSettings, SettingsConfigDict
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    from dataclasses import dataclass, field

CONFIG_FILE_PATH = Path(__file__).resolve().parent.parent / "config.json"


if PYDANTIC_AVAILABLE:
    class LLMConfig(BaseModel):
        provider: str = Field(default="gemini", description="ollama | gemini | gemini_cli | llamacpp | transformers")
        model_name: str = Field(default="gemini-2.5-flash")
        gemini_api_key: Optional[str] = Field(default="", description="Google Gemini API Key")
        ollama_base_url: str = Field(default="http://127.0.0.1:11434")
        ollama_model: str = Field(default="qwen2.5:3b")
        llamacpp_model_path: Optional[str] = Field(default=None)
        hf_model_id: str = Field(default="Qwen/Qwen2-1.5B-Instruct")
        temperature: float = Field(default=0.2)
        max_tokens: int = Field(default=1024)
        request_timeout: float = Field(default=30.0)

    class SafetyConfig(BaseModel):
        strict_mode: bool = Field(default=True)
        require_approval_for_delete: bool = Field(default=True)
        require_approval_for_executables: bool = Field(default=True)
        require_approval_for_admin: bool = Field(default=True)
        blocked_keywords: List[str] = Field(
            default_factory=lambda: [
                "format",
                "reg add",
                "reg delete",
                "diskpart",
                "rmdir /s /q c:\\",
                "rmdir /s /q c:\\windows",
            ]
        )

    class AppConfig(BaseSettings):
        model_config = SettingsConfigDict(
            env_prefix="AGENT_",
            env_nested_delimiter="__",
            extra="ignore"
        )

        app_name: str = "Desktop AI Agent"
        version: str = "1.0.0"
        environment: str = "development"
        capture_interval: float = 1.0
        ocr_engine: str = "hybrid"
        max_retries: int = 3
        memory_limit: int = 50
        teacher_enabled: bool = True
        gemini_cli_enabled: bool = False
        gemini_cli_timeout: float = 45.0
        gemini_cli_model: str = "flash"
        db_path: str = "agent/memory/memory.db"
        log_level: str = "INFO"

        llm: LLMConfig = Field(default_factory=LLMConfig)
        safety: SafetyConfig = Field(default_factory=SafetyConfig)

else:
    # Pure Python fallback if pydantic-settings is not yet installed
    @dataclass
    class LLMConfig:
        provider: str = "gemini"
        model_name: str = "gemini-2.5-flash"
        gemini_api_key: Optional[str] = ""
        ollama_base_url: str = "http://127.0.0.1:11434"
        ollama_model: str = "qwen2.5:3b"
        llamacpp_model_path: Optional[str] = None
        hf_model_id: str = "Qwen/Qwen2-1.5B-Instruct"
        temperature: float = 0.2
        max_tokens: int = 1024
        request_timeout: float = 30.0

    @dataclass
    class SafetyConfig:
        strict_mode: bool = True
        require_approval_for_delete: bool = True
        require_approval_for_executables: bool = True
        require_approval_for_admin: bool = True
        blocked_keywords: List[str] = field(default_factory=lambda: [
            "format", "reg add", "reg delete", "diskpart", "rmdir /s /q c:\\"
        ])

    @dataclass
    class AppConfig:
        app_name: str = "Desktop AI Agent"
        version: str = "1.0.0"
        environment: str = "development"
        capture_interval: float = 1.0
        ocr_engine: str = "hybrid"
        max_retries: int = 3
        memory_limit: int = 50
        teacher_enabled: bool = True
        gemini_cli_enabled: bool = False
        gemini_cli_timeout: float = 45.0
        gemini_cli_model: str = "flash"
        db_path: str = "agent/memory/memory.db"
        log_level: str = "INFO"
        llm: LLMConfig = field(default_factory=LLMConfig)
        safety: SafetyConfig = field(default_factory=SafetyConfig)


def _deep_merge(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively deep-merge two dictionaries."""
    result = dict(base)
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load configuration with precedence (highest first):
    1. Environment variables: AGENT_LLM__GEMINI_API_KEY, GEMINI_API_KEY, GOOGLE_API_KEY
    2. config.local.json (git-ignored, deep-merged over config.json)
    3. config.json
    """
    target_path = config_path or CONFIG_FILE_PATH
    data: Dict[str, Any] = {}

    # 3. Base: config.json
    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[Config] Error loading {target_path.name}: {e}, using default config")

    # 2. Deep-merge config.local.json if it exists alongside config.json
    local_path = target_path.parent / "config.local.json"
    if local_path.exists():
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                local_data = json.load(f)
            data = _deep_merge(data, local_data)
        except Exception as e:
            print(f"[Config] Error loading {local_path.name}: {e}")

    # Normalize flat api_key or gemini_api_key into llm.gemini_api_key
    top_key = data.pop("api_key", None) or data.pop("gemini_api_key", None)
    if top_key:
        if "llm" not in data or not isinstance(data["llm"], dict):
            data["llm"] = {}
        if not data["llm"].get("gemini_api_key"):
            data["llm"]["gemini_api_key"] = str(top_key).strip()

    # 1. Environment variable override (highest precedence)
    env_api_key = (
        os.environ.get("AGENT_LLM__GEMINI_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if env_api_key:
        if "llm" not in data or not isinstance(data["llm"], dict):
            data["llm"] = {}
        data["llm"]["gemini_api_key"] = env_api_key.strip()

    try:
        if PYDANTIC_AVAILABLE:
            return AppConfig.model_validate(data)
        else:
            llm_data = data.get("llm", {})
            safety_data = data.get("safety", {})
            llm_cfg = LLMConfig(**llm_data) if llm_data else LLMConfig()
            safety_cfg = SafetyConfig(**safety_data) if safety_data else SafetyConfig()
            clean_data = {k: v for k, v in data.items() if k not in ("llm", "safety")}
            return AppConfig(llm=llm_cfg, safety=safety_cfg, **clean_data)
    except Exception as e:
        print(f"[Config] Validation error: {e}, using default config")
        return AppConfig()


# Global config singleton
settings = load_config()

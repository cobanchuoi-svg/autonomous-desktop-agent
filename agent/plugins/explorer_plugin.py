"""
Windows File Explorer plugin conforming to TDD Section 17.
"""

from pathlib import Path
import subprocess
from typing import Any
from agent.plugins.base import BasePlugin, PluginMetadata
from agent.logger import logger


class ExplorerPlugin(BasePlugin):
    """Plugin for Windows File Explorer interactions."""

    def __init__(self):
        super().__init__(
            metadata=PluginMetadata(
                name="explorer_plugin",
                description="Controls Windows File Explorer windows and directories",
                supported_actions=["open_folder", "select_file"],
            )
        )

    def initialize(self) -> bool:
        self._is_initialized = True
        logger.info("[ExplorerPlugin] Initialized.")
        return True

    def execute(self, action_name: str, **kwargs: Any) -> Any:
        if not self._is_initialized:
            self.initialize()

        if action_name == "open_folder":
            folder = kwargs.get("path", ".")
            subprocess.Popen(["explorer", str(Path(folder).resolve())], shell=True)
            return {"status": "success", "folder": folder}
        elif action_name == "select_file":
            file_path = kwargs.get("file", "")
            subprocess.Popen(["explorer", f"/select,{Path(file_path).resolve()}"], shell=True)
            return {"status": "success", "selected": file_path}
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def shutdown(self) -> None:
        self._is_initialized = False
        logger.info("[ExplorerPlugin] Shutdown.")

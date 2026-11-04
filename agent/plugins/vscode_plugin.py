"""
VS Code workspace automation plugin conforming to TDD Section 17.
"""

from pathlib import Path
import subprocess
from typing import Any
from agent.plugins.base import BasePlugin, PluginMetadata
from agent.logger import logger


class VSCodePlugin(BasePlugin):
    """Plugin for controlling Visual Studio Code workspace and opening files."""

    def __init__(self):
        super().__init__(
            metadata=PluginMetadata(
                name="vscode_plugin",
                description="Automates Visual Studio Code project launching and file editing",
                supported_actions=["open_project", "open_file", "new_window"],
            )
        )

    def initialize(self) -> bool:
        self._is_initialized = True
        logger.info("[VSCodePlugin] Initialized.")
        return True

    def execute(self, action_name: str, **kwargs: Any) -> Any:
        if not self._is_initialized:
            self.initialize()

        if action_name == "open_project":
            project_path = kwargs.get("path", ".")
            proc = subprocess.Popen(["code", str(Path(project_path).resolve())], shell=True)
            return {"status": "success", "pid": proc.pid, "project": project_path}
        elif action_name == "open_file":
            file_path = kwargs.get("file", "")
            proc = subprocess.Popen(["code", "-g", str(Path(file_path).resolve())], shell=True)
            return {"status": "success", "pid": proc.pid, "file": file_path}
        elif action_name == "new_window":
            proc = subprocess.Popen(["code", "-n"], shell=True)
            return {"status": "success", "pid": proc.pid}
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def shutdown(self) -> None:
        self._is_initialized = False
        logger.info("[VSCodePlugin] Shutdown.")

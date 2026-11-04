"""
Browser automation plugin conforming to TDD Section 17.
"""

import subprocess
import webbrowser
from typing import Any
from agent.plugins.base import BasePlugin, PluginMetadata
from agent.logger import logger


class BrowserPlugin(BasePlugin):
    """Plugin providing browser navigation and URL launching."""

    def __init__(self):
        super().__init__(
            metadata=PluginMetadata(
                name="browser_plugin",
                description="Controls and automates web browser operations",
                supported_actions=["open_url", "search_google", "launch_chrome"],
            )
        )

    def initialize(self) -> bool:
        self._is_initialized = True
        logger.info("[BrowserPlugin] Initialized.")
        return True

    def execute(self, action_name: str, **kwargs: Any) -> Any:
        if not self._is_initialized:
            self.initialize()

        if action_name == "open_url":
            url = kwargs.get("url", "https://google.com")
            webbrowser.open(url)
            return {"status": "success", "url": url}
        elif action_name == "search_google":
            query = kwargs.get("query", "")
            search_url = f"https://www.google.com/search?q={query}"
            webbrowser.open(search_url)
            return {"status": "success", "search": query}
        elif action_name == "launch_chrome":
            from agent.actions.application import ApplicationController
            app_res = ApplicationController().launch_app("chrome")
            return {"status": "success" if app_res.success else "error", "message": app_res.message or app_res.error}
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def shutdown(self) -> None:
        self._is_initialized = False
        logger.info("[BrowserPlugin] Shutdown.")

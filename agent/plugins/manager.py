"""
Plugin Manager registering, discovering, and executing plugins.
"""

from typing import Any, Dict, List, Optional
from agent.plugins.base import BasePlugin
from agent.logger import logger


class PluginManager:
    """Central registry and execution router for agent plugins."""

    def __init__(self):
        self._plugins: Dict[str, BasePlugin] = {}

    def register_plugin(self, plugin: BasePlugin) -> None:
        """Register a plugin instance."""
        name = plugin.metadata.name
        self._plugins[name] = plugin
        plugin.initialize()
        logger.info(f"[PluginManager] Registered plugin: {name} (actions: {plugin.metadata.supported_actions})")

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        return self._plugins.get(name)

    def list_plugins(self) -> List[str]:
        return list(self._plugins.keys())

    def execute_action(self, plugin_name: str, action_name: str, **kwargs: Any) -> Any:
        plugin = self.get_plugin(plugin_name)
        if not plugin:
            raise KeyError(f"Plugin '{plugin_name}' is not registered.")
        return plugin.execute(action_name, **kwargs)

    def shutdown_all(self) -> None:
        for p in self._plugins.values():
            try:
                p.shutdown()
            except Exception as e:
                logger.error(f"[PluginManager] Error shutting down {p.metadata.name}: {e}")
        self._plugins.clear()

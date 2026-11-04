"""
Plugins package.
"""

from agent.plugins.base import BasePlugin, PluginMetadata
from agent.plugins.browser_plugin import BrowserPlugin
from agent.plugins.vscode_plugin import VSCodePlugin
from agent.plugins.explorer_plugin import ExplorerPlugin
from agent.plugins.manager import PluginManager

__all__ = [
    "BasePlugin",
    "PluginMetadata",
    "BrowserPlugin",
    "VSCodePlugin",
    "ExplorerPlugin",
    "PluginManager",
]

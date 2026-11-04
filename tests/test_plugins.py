"""
Unit tests for Plugin interface and Plugin Manager.
"""

from agent.plugins.manager import PluginManager
from agent.plugins.browser_plugin import BrowserPlugin
from agent.plugins.vscode_plugin import VSCodePlugin
from agent.plugins.explorer_plugin import ExplorerPlugin


def test_plugin_registration_and_execution():
    pm = PluginManager()
    browser = BrowserPlugin()
    vscode = VSCodePlugin()
    explorer = ExplorerPlugin()

    pm.register_plugin(browser)
    pm.register_plugin(vscode)
    pm.register_plugin(explorer)

    assert "browser_plugin" in pm.list_plugins()
    assert "vscode_plugin" in pm.list_plugins()
    assert "explorer_plugin" in pm.list_plugins()

    # Verify plugin retrieval
    retrieved = pm.get_plugin("browser_plugin")
    assert retrieved is not None
    assert "open_url" in retrieved.metadata.supported_actions

    pm.shutdown_all()
    assert len(pm.list_plugins()) == 0

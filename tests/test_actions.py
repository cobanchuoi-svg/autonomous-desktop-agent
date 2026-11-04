"""
Unit tests for Actions, Safety Guard, and Dispatcher.
"""

import pytest
from agent.actions.base import ActionCommand, ActionType
from agent.actions.safety import SafetyGuard
from agent.actions import ActionDispatcher
from agent.config import SafetyConfig
from agent.core.exceptions import SafetyViolationException


def test_safety_guard_blocks_dangerous_commands():
    guard = SafetyGuard(SafetyConfig())

    # Format drive
    cmd_format = ActionCommand(
        action_type=ActionType.LAUNCH_APP,
        params={"app_name": "cmd", "args": ["format c:"]},
    )
    is_safe, reason, _ = guard.validate(cmd_format)
    assert not is_safe
    assert "blocked by safety policy" in reason

    # Registry modification
    cmd_reg = ActionCommand(
        action_type=ActionType.LAUNCH_APP,
        params={"app_name": "reg add HKLM\\Software"},
    )
    is_safe, reason, _ = guard.validate(cmd_reg)
    assert not is_safe

    with pytest.raises(SafetyViolationException):
        guard.check_or_raise(cmd_reg)


def test_safety_guard_permits_safe_actions():
    guard = SafetyGuard(SafetyConfig())

    safe_click = ActionCommand(
        action_type=ActionType.CLICK,
        params={"x": 500, "y": 300, "button": "left"},
    )
    is_safe, reason, _ = guard.validate(safe_click)
    assert is_safe


def test_action_dispatcher_wait():
    dispatcher = ActionDispatcher()
    cmd_wait = ActionCommand(
        action_type=ActionType.WAIT,
        params={"seconds": 0.05},
    )
    result = dispatcher.dispatch(cmd_wait)
    assert result.success
    assert result.action_type == ActionType.WAIT


def test_windows_app_resolver_finds_chrome_and_notepad():
    from agent.actions.application import WindowsAppResolver
    resolver = WindowsAppResolver()
    chrome_path = resolver.resolve("chrome")
    assert chrome_path is not None
    assert "chrome.exe" in chrome_path.lower()

    notepad_path = resolver.resolve("notepad")
    assert notepad_path is not None
    assert "notepad.exe" in notepad_path.lower()


def test_windows_app_resolver_fails_gracefully_on_missing_app():
    from agent.actions.application import WindowsAppResolver, ApplicationController
    resolver = WindowsAppResolver()
    nonexistent = resolver.resolve("non_existent_app_12345")
    assert nonexistent is None

    ctrl = ApplicationController()
    res = ctrl.launch_app("non_existent_app_12345")
    assert res.success is False
    assert "could not be located" in res.error


def test_state_validator_launch_app_verification():
    from agent.verifier.state_validator import StateValidator
    validator = StateValidator()
    # Missing process validation fails
    res_fail = validator.validate_action_effect(
        before_frame=None,
        after_frame=None,
        action_type="launch_app",
        expected_text="non_existent_process_xyz",
    )
    assert res_fail.is_valid is False
    assert "was not launched" in res_fail.reason


"""
Safety Layer enforcing security boundaries, blocked commands, and approval checks.
"""

import re
from typing import List, Tuple
from agent.actions.base import ActionCommand, ActionType
from agent.config import SafetyConfig
from agent.core.exceptions import SafetyViolationException
from agent.logger import logger


class SafetyGuard:
    """Validates actions before execution against security policies."""

    BLOCKED_PATTERNS = [
        r"format\s+[a-zA-Z]:",
        r"diskpart",
        r"reg\s+(add|delete|import)",
        r"rmdir\s+/[sS]\s+/[qQ]\s+[cC]:",
        r"del\s+/[fF]\s+/[sS]\s+/[qQ]\s+[cC]:\\windows",
        r"shutdown\s+/[sS]",
        r"powershell\s+-enc",
        r"mimikatz",
    ]

    APPROVAL_REQUIRED_PATTERNS = [
        r"(del|rm|unlink)\s+",
        r"runas\s+",
        r"net\s+user",
        r"taskkill\s+/f",
        r"install|pip\s+install|winget",
    ]

    def __init__(self, config: SafetyConfig):
        self.config = config

    def validate(self, command: ActionCommand) -> Tuple[bool, str, bool]:
        """
        Validate an action.
        Returns:
            (is_allowed: bool, reason: str, requires_approval: bool)
        """
        # 1. Collect all string values from params (including nested lists)
        string_values = []
        for val in command.params.values():
            if isinstance(val, str):
                string_values.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        string_values.append(item)

        # Check for blocked actions
        for text in string_values:
            for pattern in self.BLOCKED_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    msg = f"Action blocked by safety policy: matches forbidden pattern '{pattern}'"
                    logger.warning(f"[SafetyGuard] {msg}")
                    return False, msg, False

            for blocked_kw in self.config.blocked_keywords:
                if blocked_kw.lower() in text.lower():
                    msg = f"Action blocked by safety policy: contains blocked keyword '{blocked_kw}'"
                    logger.warning(f"[SafetyGuard] {msg}")
                    return False, msg, False

        # 2. Check for actions requiring manual confirmation/approval
        if command.action_type in (ActionType.KILL_APP, ActionType.WRITE_FILE):
            if self.config.require_approval_for_delete:
                for text in string_values:
                    for pattern in self.APPROVAL_REQUIRED_PATTERNS:
                        if re.search(pattern, text, re.IGNORECASE):
                            return True, "Requires manual user approval", True

        return True, "Safe to execute", False

    def check_or_raise(self, command: ActionCommand) -> bool:
        """Helper that raises SafetyViolationException if action is forbidden."""
        allowed, reason, requires_approval = self.validate(command)
        if not allowed:
            raise SafetyViolationException(reason)
        return requires_approval

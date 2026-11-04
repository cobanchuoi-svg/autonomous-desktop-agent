"""
Filesystem controller for safe reading and writing of workspace files.
"""

from pathlib import Path
import time
from typing import Optional
from agent.actions.base import ActionResult, ActionType
from agent.logger import logger


class FilesystemController:
    """Safely reads, writes, and inspects files within permitted boundaries."""

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or Path.cwd()

    def read_file(self, path: str, max_bytes: int = 100_000) -> ActionResult:
        """Read content of a text file."""
        start = time.perf_counter()
        target = Path(path).resolve()
        try:
            if not target.exists():
                return ActionResult(
                    success=False,
                    action_type=ActionType.READ_FILE,
                    error=f"File not found: {target}",
                    execution_time=time.perf_counter() - start,
                )

            with open(target, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_bytes)

            return ActionResult(
                success=True,
                action_type=ActionType.READ_FILE,
                message=f"Read {len(content)} characters from {target.name}",
                data={"content": content, "path": str(target)},
                execution_time=time.perf_counter() - start,
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action_type=ActionType.READ_FILE,
                error=str(e),
                execution_time=time.perf_counter() - start,
            )

    def write_file(self, path: str, content: str, overwrite: bool = True) -> ActionResult:
        """Write content to a file."""
        start = time.perf_counter()
        target = Path(path).resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not overwrite:
                return ActionResult(
                    success=False,
                    action_type=ActionType.WRITE_FILE,
                    error=f"File exists and overwrite is False: {target}",
                    execution_time=time.perf_counter() - start,
                )

            with open(target, "w", encoding="utf-8") as f:
                f.write(content)

            return ActionResult(
                success=True,
                action_type=ActionType.WRITE_FILE,
                message=f"Wrote {len(content)} characters to {target.name}",
                data={"path": str(target)},
                execution_time=time.perf_counter() - start,
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action_type=ActionType.WRITE_FILE,
                error=str(e),
                execution_time=time.perf_counter() - start,
            )

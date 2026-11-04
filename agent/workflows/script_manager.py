"""
ScriptManager — Manages human-approved dynamic Python scripts for unfamiliar tasks.
Enforces strict safety verification, human review before execution, and isolated subprocess execution.
"""

import os
import re
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.logger import logger


class ScriptManager:
    """Manages drafting, safety checking, and controlled execution of user-approved Python scripts."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).resolve().parents[1] / "scripts"
        self.drafts_dir = self.base_dir / "drafts"
        self.archive_dir = self.base_dir / "archive"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def generate_task_id() -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"task_{timestamp}"

    @staticmethod
    def validate_code(code: str) -> Tuple[bool, str]:
        """Verify code doesn't contain dangerous destructive system operations."""
        forbidden_patterns = [
            r"format\s+[a-zA-Z]:",
            r"diskpart",
            r"reg\s+(add|delete|import)",
            r"rmdir\s+/[sS]",
            r"del\s+/[fF].*windows",
            r"shutil\.rmtree\s*\(\s*['\"](?:[cC]:[\\/]|/)",
            r"os\.system\s*\(\s*['\"].*rmdir",
            r"os\.remove\s*\(\s*['\"][cC]:[\\/]",
            r"mimikatz",
        ]
        for pattern in forbidden_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                return False, f"Code contains blocked forbidden pattern: '{pattern}'"
        return True, "Code passed basic safety validation."

    def create_draft(self, code: str, title: str = "", task_id: Optional[str] = None) -> Dict[str, Any]:
        """Save a new script draft for human review. Never executed automatically."""
        task_id = task_id or self.generate_task_id()
        is_safe, reason = self.validate_code(code)
        if not is_safe:
            raise ValueError(f"Safety Check Failed: {reason}")

        # Clean markdown fences if LLM generated them
        clean_code = code.strip()
        if clean_code.startswith("```"):
            clean_code = clean_code.split("\n", 1)[-1]
            if "```" in clean_code:
                clean_code = clean_code.rsplit("```", 1)[0]
            clean_code = clean_code.strip()

        file_path = self.drafts_dir / f"{task_id}.py"
        header = f"# Task: {title or task_id}\n# Generated: {datetime.now().isoformat()}\n# Status: Pending Human Approval\n\n"
        full_content = header + clean_code

        file_path.write_text(full_content, encoding="utf-8")
        logger.info(f"[ScriptManager] Draft saved for human approval: {file_path}")

        return {
            "task_id": task_id,
            "title": title or task_id,
            "code": clean_code,
            "file_path": str(file_path),
            "status": "pending_approval",
        }

    def execute_draft(self, task_id: str, timeout: float = 45.0) -> Dict[str, Any]:
        """Execute an approved script draft in a separate subprocess."""
        file_path = self.drafts_dir / f"{task_id}.py"
        if not file_path.exists():
            # Check if it was already archived
            archived = self.archive_dir / f"{task_id}.py"
            if archived.exists():
                file_path = archived
            else:
                raise FileNotFoundError(f"No draft script found for task ID: '{task_id}'")

        code = file_path.read_text(encoding="utf-8")
        is_safe, reason = self.validate_code(code)
        if not is_safe:
            raise ValueError(f"Pre-execution Safety Check Failed: {reason}")

        start_time = time.time()
        logger.info(f"[ScriptManager] Executing user-approved script: {file_path}")

        try:
            completed = subprocess.run(
                [sys.executable, str(file_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=str(self.base_dir),
            )
            duration = round(time.time() - start_time, 2)
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()
            success = (completed.returncode == 0)

            # Archive the script after execution
            dest = self.archive_dir / f"{task_id}.py"
            try:
                file_path.replace(dest)
            except Exception:
                pass

            return {
                "task_id": task_id,
                "success": success,
                "exit_code": completed.returncode,
                "duration_seconds": duration,
                "stdout": stdout,
                "stderr": stderr,
                "output": stdout or stderr or ("(Executed cleanly with no output)" if success else "(Failed with no output)"),
            }
        except subprocess.TimeoutExpired:
            return {
                "task_id": task_id,
                "success": False,
                "exit_code": -1,
                "duration_seconds": timeout,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout} seconds.",
                "output": f"Execution timed out after {timeout} seconds.",
            }
        except Exception as exc:
            return {
                "task_id": task_id,
                "success": False,
                "exit_code": -1,
                "duration_seconds": round(time.time() - start_time, 2),
                "stdout": "",
                "stderr": str(exc),
                "output": f"Execution failed: {exc}",
            }

    def delete_draft(self, task_id: str) -> bool:
        """Discard and delete a draft script."""
        file_path = self.drafts_dir / f"{task_id}.py"
        if file_path.exists():
            file_path.unlink()
            logger.info(f"[ScriptManager] Draft deleted by user: {task_id}")
            return True
        return False

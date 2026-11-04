"""
Unit tests for ScriptManager safety, drafting, execution, and human approval workflow.
"""

import tempfile
from pathlib import Path
import pytest

from agent.workflows.script_manager import ScriptManager


def test_safety_validation_blocks_dangerous_code():
    sm = ScriptManager()

    # Blocked patterns
    assert not sm.validate_code("import os; os.system('format C:')")[0]
    assert not sm.validate_code("import shutil; shutil.rmtree('C:\\Windows')")[0]
    assert not sm.validate_code("del /f /s /q C:\\windows")[0]

    # Safe code
    assert sm.validate_code("import webbrowser\nwebbrowser.open('https://google.com')")[0]
    assert sm.validate_code("print('Hello from approved script')")[0]


def test_create_execute_and_delete_draft():
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = ScriptManager(base_dir=Path(tmpdir))

        # 1. Create draft
        safe_code = "print('Calculated:', 21 * 2)"
        draft = sm.create_draft(code=safe_code, title="Multiply test", task_id="test_task_1")
        assert draft["task_id"] == "test_task_1"
        assert Path(draft["file_path"]).exists()

        # 2. Execute draft
        result = sm.execute_draft("test_task_1")
        assert result["success"] is True
        assert "Calculated: 42" in result["stdout"]
        assert result["exit_code"] == 0

        # After execution, draft should be archived
        assert (sm.archive_dir / "test_task_1.py").exists()


def test_delete_draft():
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = ScriptManager(base_dir=Path(tmpdir))
        draft = sm.create_draft(code="print('to be deleted')", task_id="to_delete")
        assert Path(draft["file_path"]).exists()

        deleted = sm.delete_draft("to_delete")
        assert deleted is True
        assert not Path(draft["file_path"]).exists()

"""
Unit tests for Memory Layer, SQLite schema, and scoring formula.
"""

from datetime import datetime, timedelta
import tempfile
from pathlib import Path
import pytest

from agent.memory.db import DatabaseManager
from agent.memory.models import MemoryEntry
from agent.memory.memory_manager import MemoryManager


def test_sqlite_schema_creation():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_memory.db"
        db = DatabaseManager(str(db_path))

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {"users", "goals", "tasks", "memory_entries", "actions", "lessons", "summaries"}
        assert expected_tables.issubset(tables)


def test_memory_scoring_formula():
    """
    TDD formula: score = importance * 0.5 + recency * 0.3 + success_rate * 0.2
    """
    # Recent entry (age = 0 hours -> recency = 1.0)
    now = datetime.utcnow()
    recent = MemoryEntry(
        content="VS Code is pinned to taskbar",
        importance=1.0,
        success_rate=1.0,
        created_at=now,
    )
    # Expected: 1.0*0.5 + 1.0*0.3 + 1.0*0.2 = 1.0
    assert recent.calculate_score(now) == 1.0

    # Half importance, half success rate
    mid = MemoryEntry(
        content="Chrome is in start menu",
        importance=0.5,
        success_rate=0.5,
        created_at=now,
    )
    # Expected: 0.5*0.5 + 1.0*0.3 + 0.5*0.2 = 0.25 + 0.3 + 0.1 = 0.65
    assert mid.calculate_score(now) == 0.65


def test_memory_manager_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_lifecycle.db"
        manager = MemoryManager(DatabaseManager(str(db_path)))

        # 1. Goal & Task creation
        goal = manager.create_goal("Test Goal")
        assert goal.id is not None
        assert manager.active_goal is not None

        tasks = manager.set_tasks_for_goal(goal.id, ["Step 1", "Step 2"])
        assert len(tasks) == 2

        # 2. Complete task
        manager.mark_task_completed(tasks[0].id)
        pending = manager.get_pending_tasks(goal.id)
        assert len(pending) == 1
        assert pending[0].description == "Step 2"

        # 3. Record Action
        act_id = manager.record_action("click", {"x": 100, "y": 200}, "success", "Clicked OK")
        assert act_id is not None
        recent_acts = manager.get_recent_actions(5)
        assert len(recent_acts) == 1
        assert recent_acts[0].action_type == "click"

        # 4. JSON Export
        export_file = Path(tmpdir) / "export.json"
        manager.export_json(export_file)
        assert export_file.exists()

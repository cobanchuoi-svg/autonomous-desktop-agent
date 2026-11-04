"""
Three-tier Memory Manager (Short-term, Working, Long-term) with relevance scoring.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from agent.memory.base import BaseMemoryManager
from agent.memory.db import DatabaseManager
from agent.memory.models import (
    ActionRecord,
    Goal,
    Lesson,
    MemoryEntry,
    SummaryRecord,
    Task,
)
from agent.logger import logger


class MemoryManager(BaseMemoryManager):
    """Coordinates working memory, short-term screen context, and SQLite long-term storage."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()
        # Short-term ephemeral memory
        self.short_term: Dict[str, Any] = {
            "last_screen_text": "",
            "last_action": None,
            "last_action_success": True,
        }
        # Working memory
        self.active_goal: Optional[Goal] = None
        self.active_tasks: List[Task] = []
        self._load_active_state()

    def _load_active_state(self) -> None:
        """Load any unfinished goal from persistent storage on startup."""
        goal = self.get_active_goal()
        if goal:
            self.active_goal = goal
            self.active_tasks = self.get_pending_tasks(goal.id)  # type: ignore
            logger.info(f"[MemoryManager] Resumed active goal: '{goal.title}' with {len(self.active_tasks)} pending tasks")

    # --- Short-Term Memory ---
    def update_short_term(self, screen_text: str, last_action: Optional[Dict[str, Any]] = None, success: bool = True) -> None:
        self.short_term["last_screen_text"] = screen_text
        if last_action:
            self.short_term["last_action"] = last_action
            self.short_term["last_action_success"] = success

    # --- Long-Term Memory Scoring & Retrieval ---
    def add_memory_entry(self, content: str, category: str = "general", importance: float = 0.5) -> int:
        """Store persistent knowledge entry."""
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memory_entries (category, content, importance, success_rate)
                VALUES (?, ?, ?, 1.0)
                """,
                (category, content, importance),
            )
            conn.commit()
            return cursor.lastrowid

    def get_top_memories(self, limit: int = 5) -> List[MemoryEntry]:
        """Fetch and score memories using TDD formula: score = imp*0.5 + rec*0.3 + succ*0.2"""
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memory_entries ORDER BY id DESC LIMIT 50")
            rows = cursor.fetchall()

        entries: List[MemoryEntry] = []
        for r in rows:
            entry = MemoryEntry(
                id=r["id"],
                category=r["category"],
                content=r["content"],
                importance=r["importance"],
                success_rate=r["success_rate"],
                created_at=datetime.fromisoformat(r["created_at"]) if isinstance(r["created_at"], str) else datetime.utcnow(),
            )
            entries.append(entry)

        # Sort descending by calculated relevance score
        entries.sort(key=lambda e: e.calculate_score(), reverse=True)
        return entries[:limit]

    # --- Goals & Tasks Management ---
    def create_goal(self, title: str) -> Goal:
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO goals (title, status) VALUES (?, 'active')",
                (title,),
            )
            conn.commit()
            goal_id = cursor.lastrowid

        goal = Goal(id=goal_id, title=title, status="active")
        self.active_goal = goal
        self.active_tasks = []
        return goal

    def get_active_goal(self) -> Optional[Goal]:
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM goals WHERE status = 'active' ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return Goal(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    status=row["status"],
                )
        return None

    def complete_goal(self, goal_id: int) -> None:
        with self.db.connection_scope() as conn:
            conn.execute(
                "UPDATE goals SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (goal_id,),
            )
            conn.commit()
        if self.active_goal and self.active_goal.id == goal_id:
            self.active_goal = None
            self.active_tasks = []

    def set_tasks_for_goal(self, goal_id: int, descriptions: List[str]) -> List[Task]:
        tasks = []
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            for idx, desc in enumerate(descriptions):
                cursor.execute(
                    "INSERT INTO tasks (goal_id, step_index, description, status) VALUES (?, ?, ?, 'pending')",
                    (goal_id, idx, desc),
                )
                tasks.append(Task(id=cursor.lastrowid, goal_id=goal_id, step_index=idx, description=desc))
            conn.commit()
        self.active_tasks = tasks
        return tasks

    def get_pending_tasks(self, goal_id: int) -> List[Task]:
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tasks WHERE goal_id = ? AND status = 'pending' ORDER BY step_index ASC",
                (goal_id,),
            )
            rows = cursor.fetchall()
            return [
                Task(id=r["id"], goal_id=r["goal_id"], step_index=r["step_index"], description=r["description"], status=r["status"])
                for r in rows
            ]

    def mark_task_completed(self, task_id: int) -> None:
        with self.db.connection_scope() as conn:
            conn.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
            conn.commit()
        self.active_tasks = [t for t in self.active_tasks if t.id != task_id]

    # --- Actions Recording ---
    def record_action(
        self,
        action_type: str,
        params: Dict[str, Any],
        status: str,
        result_message: str = "",
        goal_id: Optional[int] = None,
    ) -> int:
        g_id = goal_id or (self.active_goal.id if self.active_goal else None)
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO actions (goal_id, action, params, status, result_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (g_id, action_type, json.dumps(params), status, result_message),
            )
            conn.commit()
            return cursor.lastrowid

    def get_recent_actions(self, limit: int = 10) -> List[ActionRecord]:
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()

        records = []
        for r in rows:
            params = json.loads(r["params"]) if r["params"] else {}
            records.append(
                ActionRecord(
                    id=r["id"],
                    goal_id=r["goal_id"],
                    action_type=r["action"],
                    params=params,
                    status=r["status"],
                    result_message=r["result_message"] or "",
                )
            )
        records.reverse()
        return records

    def get_total_action_count(self) -> int:
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM actions")
            return cursor.fetchone()[0]

    # --- Lessons ---
    def add_lesson(self, lesson_text: str, confidence: float = 0.8, source: str = "teacher_ai") -> int:
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO lessons (lesson, confidence, source) VALUES (?, ?, ?)",
                (lesson_text, confidence, source),
            )
            conn.commit()
            return cursor.lastrowid

    def get_recent_lessons(self, limit: int = 5) -> List[Lesson]:
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM lessons ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [
                Lesson(id=r["id"], lesson=r["lesson"], confidence=r["confidence"], source=r["source"])
                for r in rows
            ]

    # --- JSON Export ---
    def export_json(self, export_path: Path) -> None:
        """Export state and memory tables to a structured JSON file."""
        export_path = Path(export_path)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "current_goal": self.active_goal.model_dump() if self.active_goal else None,
            "pending_tasks": [t.model_dump() for t in self.active_tasks],
            "short_term": self.short_term,
            "top_memories": [m.model_dump() for m in self.get_top_memories(10)],
            "recent_actions": [a.model_dump() for a in self.get_recent_actions(20)],
            "recent_lessons": [l.model_dump() for l in self.get_recent_lessons(10)],
            "exported_at": datetime.utcnow().isoformat(),
        }
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"[MemoryManager] Exported memory snapshot to {export_path}")

    # --- FSM State Persistence ---
    def save_agent_state(
        self,
        current_state: str,
        goal_id: Optional[int] = None,
        step_index: int = 0,
        context_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist current FSM state to SQLite for resume-after-restart capability."""
        with self.db.connection_scope() as conn:
            conn.execute(
                """
                INSERT INTO agent_state (id, current_state, goal_id, step_index, context_json, updated_at)
                VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    current_state=excluded.current_state,
                    goal_id=excluded.goal_id,
                    step_index=excluded.step_index,
                    context_json=excluded.context_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (current_state, goal_id, step_index, json.dumps(context_data or {})),
            )
            conn.commit()

    def load_agent_state(self) -> Dict[str, Any]:
        """Load persisted FSM state and context."""
        with self.db.connection_scope() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT current_state, goal_id, step_index, context_json, updated_at FROM agent_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                ctx = json.loads(row["context_json"]) if row["context_json"] else {}
                return {
                    "current_state": row["current_state"],
                    "goal_id": row["goal_id"],
                    "step_index": row["step_index"],
                    "context": ctx,
                    "updated_at": row["updated_at"],
                }
        return {"current_state": "IDLE", "goal_id": None, "step_index": 0, "context": {}}


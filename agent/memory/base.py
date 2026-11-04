"""
Abstract interfaces for Memory and Persistence.
Clean Architecture Persistence Port.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional
from agent.memory.models import ActionRecord, Goal, Lesson, MemoryEntry, Task


class BaseDatabase(ABC):
    """Abstract interface for low-level database operations."""

    @abstractmethod
    def get_connection(self) -> Any:
        """Provide a database connection."""
        pass

    @abstractmethod
    def init_db(self) -> None:
        """Initialize database schema."""
        pass


class BaseMemoryManager(ABC):
    """Abstract interface for high-level memory operations."""

    @abstractmethod
    def update_short_term(self, screen_text: str, last_action: Optional[Dict[str, Any]] = None, success: bool = True) -> None:
        pass

    @abstractmethod
    def add_memory_entry(self, content: str, category: str = "general", importance: float = 0.5) -> int:
        pass

    @abstractmethod
    def get_top_memories(self, limit: int = 5) -> List[MemoryEntry]:
        pass

    @abstractmethod
    def create_goal(self, title: str) -> Goal:
        pass

    @abstractmethod
    def get_active_goal(self) -> Optional[Goal]:
        pass

    @abstractmethod
    def complete_goal(self, goal_id: int) -> None:
        pass

    @abstractmethod
    def set_tasks_for_goal(self, goal_id: int, descriptions: List[str]) -> List[Task]:
        pass

    @abstractmethod
    def get_pending_tasks(self, goal_id: int) -> List[Task]:
        pass

    @abstractmethod
    def mark_task_completed(self, task_id: int) -> None:
        pass

    @abstractmethod
    def record_action(
        self,
        action_type: str,
        params: Dict[str, Any],
        status: str,
        result_message: str = "",
        goal_id: Optional[int] = None,
    ) -> int:
        pass

    @abstractmethod
    def get_recent_actions(self, limit: int = 10) -> List[ActionRecord]:
        pass

    @abstractmethod
    def add_lesson(self, lesson_text: str, confidence: float = 0.8, source: str = "teacher_ai") -> int:
        pass

    @abstractmethod
    def get_recent_lessons(self, limit: int = 5) -> List[Lesson]:
        pass

    @abstractmethod
    def export_json(self, export_path: Path) -> None:
        pass

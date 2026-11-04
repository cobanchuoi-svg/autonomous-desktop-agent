"""
Data models for the SQLite memory system.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    """General long-term memory entry with relevance scoring attributes."""
    id: Optional[int] = None
    category: str = "general"
    content: str
    importance: float = 0.5  # 0.0 to 1.0
    success_rate: float = 1.0  # 0.0 to 1.0
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def calculate_score(self, current_time: Optional[datetime] = None) -> float:
        """
        TDD Formula:
        score = importance * 0.5 + recency * 0.3 + success_rate * 0.2
        """
        now = current_time or datetime.utcnow()
        age_hours = max((now - self.created_at).total_seconds() / 3600.0, 0.0)
        # Recency decay over 48 hours: 1.0 at age=0, down to 0.1 at age=48+
        recency = max(0.1, 1.0 - (age_hours / 48.0))

        score = (self.importance * 0.5) + (recency * 0.3) + (self.success_rate * 0.2)
        return round(score, 4)


class Goal(BaseModel):
    id: Optional[int] = None
    user_id: int = 1
    title: str
    status: str = "active"  # active, completed, failed, paused
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class Task(BaseModel):
    id: Optional[int] = None
    goal_id: int
    step_index: int = 0
    description: str
    status: str = "pending"  # pending, in_progress, completed, failed
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ActionRecord(BaseModel):
    id: Optional[int] = None
    goal_id: Optional[int] = None
    action_type: str
    params: Dict[str, Any] = Field(default_factory=dict)
    status: str = "success"  # success, failure
    result_message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Lesson(BaseModel):
    id: Optional[int] = None
    lesson: str
    confidence: float = 0.8
    source: str = "teacher_ai"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SummaryRecord(BaseModel):
    id: Optional[int] = None
    summary: str
    action_count: int = 50
    created_at: datetime = Field(default_factory=datetime.utcnow)

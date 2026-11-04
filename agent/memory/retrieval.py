"""
Memory Retrieval Engine.
Scores and retrieves only relevant episodic knowledge without loading the full database.
"""

from typing import Any, Dict, List, Optional
from agent.memory.memory_manager import MemoryManager
from agent.memory.models import MemoryEntry
from agent.logger import logger


class MemoryRetrievalEngine:
    """Extracts top relevant memory entries based on current Goal, Screen Text, and Recent Actions."""

    def __init__(self, memory_manager: MemoryManager):
        self.memory = memory_manager

    def retrieve_relevant(
        self,
        goal: str,
        screen_text: str,
        recent_actions: Optional[List[Dict[str, Any]]] = None,
        limit: int = 5,
    ) -> List[MemoryEntry]:
        """
        Score memories based on keyword relevance to Goal and Screen Text,
        combined with the TDD formula (importance * 0.5 + recency * 0.3 + success * 0.2).
        """
        all_candidates = self.memory.get_top_memories(limit=30)
        scored_candidates: List[tuple[float, MemoryEntry]] = []

        goal_tokens = set(goal.lower().split())
        screen_tokens = set(screen_text.lower().split())

        for entry in all_candidates:
            base_score = entry.calculate_score()
            content_lower = entry.content.lower()

            # Keyword matching bonus
            relevance_bonus = 0.0
            for gt in goal_tokens:
                if len(gt) > 2 and gt in content_lower:
                    relevance_bonus += 0.3

            for st in screen_tokens:
                if len(st) > 3 and st in content_lower:
                    relevance_bonus += 0.1

            total_score = base_score + relevance_bonus
            scored_candidates.append((total_score, entry))

        # Sort descending by total score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        top_entries = [entry for _, entry in scored_candidates[:limit]]
        logger.debug(f"[RetrievalEngine] Retrieved {len(top_entries)} relevant memories for goal: '{goal}'")
        return top_entries

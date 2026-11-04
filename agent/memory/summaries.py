"""
Periodic summarization and lesson generation every 50 actions.
"""

from typing import Optional
from agent.memory.memory_manager import MemoryManager
from agent.logger import logger


class Summarizer:
    """Monitors action count and triggers high-level operational summaries."""

    def __init__(self, memory_manager: MemoryManager, trigger_interval: int = 50):
        self.memory = memory_manager
        self.trigger_interval = trigger_interval
        self._last_summarized_count = 0

    def check_and_summarize(self, total_actions: int) -> Optional[str]:
        """If 50 new actions occurred, generate and store a summary."""
        if total_actions - self._last_summarized_count >= self.trigger_interval:
            self._last_summarized_count = total_actions
            return self._generate_summary(total_actions)
        return None

    def _generate_summary(self, total_actions: int) -> str:
        recent = self.memory.get_recent_actions(self.trigger_interval)
        successes = sum(1 for a in recent if a.status == "success")
        rate = (successes / len(recent)) * 100 if recent else 100.0

        summary_text = (
            f"Checkpoint at {total_actions} actions: "
            f"{len(recent)} recent actions executed with {rate:.1f}% success rate. "
            f"Common operations: {[a.action_type for a in recent[:5]]}."
        )

        with self.memory.db.connection_scope() as conn:
            conn.execute(
                "INSERT INTO summaries (summary, action_count) VALUES (?, ?)",
                (summary_text, total_actions),
            )

        logger.info(f"[Summarizer] Generated checkpoint summary: {summary_text}")
        return summary_text

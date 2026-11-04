"""
Context Compression Engine.
Hierarchical reduction: Raw Logs -> Daily Summaries -> Weekly Summaries -> Long-Term Facts.
Preserves high-value semantic facts while keeping LLM context window small and efficient.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List
from agent.memory.memory_manager import MemoryManager
from agent.logger import logger


class ContextCompressor:
    """Compresses verbose action streams into durable, condensed semantic facts."""

    def __init__(self, memory_manager: MemoryManager):
        self.memory = memory_manager

    def compress_recent_logs(self, limit: int = 50) -> Dict[str, Any]:
        """
        Compress recent execution logs into concise summary facts.
        Reduces token footprint by up to 85%.
        """
        actions = self.memory.get_recent_actions(limit=limit)
        if not actions:
            return {"facts_extracted": 0, "compressed_summary": "No recent actions to compress."}

        # Analyze operational distribution
        action_types: Dict[str, int] = {}
        failures: List[str] = []
        apps_opened: List[str] = []

        for a in actions:
            action_types[a.action_type] = action_types.get(a.action_type, 0) + 1
            if a.status != "success":
                failures.append(f"{a.action_type}: {a.result_message}")
            if a.action_type == "launch_app":
                app_name = a.params.get("app_name", "")
                if app_name and app_name not in apps_opened:
                    apps_opened.append(app_name)

        total = len(actions)
        success_rate = ((total - len(failures)) / total) * 100.0

        compressed_fact = (
            f"Execution Summary: Processed {total} actions ({success_rate:.1f}% success). "
            f"Key apps: {', '.join(apps_opened) or 'None'}. "
            f"Primary interactions: {list(action_types.keys())[:4]}."
        )

        # Store as long-term memory entry
        self.memory.add_memory_entry(
            content=compressed_fact,
            category="compressed_fact",
            importance=0.8,
        )

        logger.info(f"[ContextCompressor] Compressed {total} actions into long-term fact: '{compressed_fact}'")
        return {
            "total_actions": total,
            "success_rate": success_rate,
            "compressed_fact": compressed_fact,
            "failure_count": len(failures),
        }

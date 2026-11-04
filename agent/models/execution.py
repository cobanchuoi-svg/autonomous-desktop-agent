"""Shared execution outcome and evidence contracts."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Evidence:
    """A concrete observation supporting an execution outcome."""

    kind: str
    value: Any
    source: str
    confidence: float = 1.0
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ExecutionResult:
    """Normalized result while preserving AgentEngine.run_goal's bool API."""

    goal: str
    success: bool
    route: str
    reason: str = ""
    evidence: List[Evidence] = field(default_factory=list)
    confidence: float = 0.0
    timings: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None


def confidence_from_evidence(evidence: List[Evidence], *, fallback: float = 0.0) -> float:
    """Return the strongest independent evidence score, bounded to [0, 1]."""
    if not evidence:
        return max(0.0, min(1.0, fallback))
    return max(0.0, min(1.0, max(item.confidence for item in evidence)))

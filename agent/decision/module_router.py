"""Select a specialized module or preserve the existing FSM fallback."""

from dataclasses import dataclass
from typing import Optional, Tuple

from agent.decision.goal_classifier import GoalCategory, GoalClassifier


@dataclass(frozen=True)
class RouteDecision:
    module: str
    category: GoalCategory
    confidence: float
    reason: str
    application: Optional[Tuple[str, str]] = None


class ModuleRouter:
    def __init__(self, classifier: GoalClassifier | None = None):
        self.classifier = classifier or GoalClassifier()

    def route(self, goal: str) -> RouteDecision:
        classification = self.classifier.classify(goal)
        if classification.category == GoalCategory.CHAT_QUERY:
            module = "chat_llm"
        elif classification.category == GoalCategory.OPEN_APP:
            module = (
                "windows_search_launcher"
                if classification.application and not classification.application[1]
                else "application_launcher"
            )
        else:
            module = "fsm"
        return RouteDecision(
            module=module,
            category=classification.category,
            confidence=classification.confidence,
            reason=classification.reason,
            application=classification.application,
        )

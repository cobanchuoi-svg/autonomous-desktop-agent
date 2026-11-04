"""Deterministic classification for the goals currently handled by fast paths."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class GoalCategory(str, Enum):
    OPEN_APP = "OPEN_APP"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    TEXT_GENERATION = "TEXT_GENERATION"
    RESEARCH = "RESEARCH"
    INFORMATION_EXTRACTION = "INFORMATION_EXTRACTION"
    FORM_FILLING = "FORM_FILLING"
    NAVIGATION = "NAVIGATION"
    VERIFICATION = "VERIFICATION"
    CHAT_QUERY = "CHAT_QUERY"
    GENERAL = "GENERAL"


@dataclass(frozen=True)
class GoalClassification:
    category: GoalCategory
    confidence: float
    application: Optional[Tuple[str, str]] = None
    reason: str = ""


class GoalClassifier:
    """Recognize exact, launch-only requests; leave ambiguous goals to the FSM."""

    APPLICATIONS = {
        "chrome": ("chrome", "chrome.exe"),
        "google chrome": ("chrome", "chrome.exe"),
        "chrome browser": ("chrome", "chrome.exe"),
        "google chrome browser": ("chrome", "chrome.exe"),
        "edge": ("msedge", "msedge.exe"),
        "microsoft edge": ("msedge", "msedge.exe"),
        "edge browser": ("msedge", "msedge.exe"),
        "microsoft edge browser": ("msedge", "msedge.exe"),
        "vs code": ("code", "code.exe"),
        "vscode": ("code", "code.exe"),
        "visual studio code": ("code", "code.exe"),
        "explorer": ("explorer", "explorer.exe"),
        "file explorer": ("explorer", "explorer.exe"),
        "windows explorer": ("explorer", "explorer.exe"),
        "notepad": ("notepad", "notepad.exe"),
    }
    LAUNCH_VERBS = {"open", "launch", "start", "run"}

    @classmethod
    def known_application_for_goal(cls, goal: str) -> Optional[Tuple[str, str]]:
        words = re.findall(r"[a-z0-9]+", goal.casefold())
        if words and words[0] == "please":
            words = words[1:]
        if len(words) < 2 or words[0] not in cls.LAUNCH_VERBS:
            return None
        return cls.APPLICATIONS.get(" ".join(words[1:]))

    def classify(self, goal: str) -> GoalClassification:
        if self._is_chat_question(goal):
            return GoalClassification(
                GoalCategory.CHAT_QUERY, 0.85, None,
                "Question-style input routes to the direct chat response path.",
            )

        application = self.known_application_for_goal(goal)
        if application:
            return GoalClassification(
                GoalCategory.OPEN_APP, 1.0, application,
                "Exact launch-only match in the known application catalog.",
            )

        words = re.findall(r"[a-z0-9]+", goal.casefold())
        if words and words[0] == "please":
            words = words[1:]
        if len(words) >= 2 and words[0] in self.LAUNCH_VERBS:
            target_words = words[1:]
            if target_words and target_words[0] == "the":
                target_words = target_words[1:]
            decoration = next((i for i, word in enumerate(target_words) if word in {"icon", "button"}), None)
            if decoration is not None:
                target_words = target_words[:decoration]
            if target_words and target_words[-1] in {"app", "application", "program"}:
                target_words = target_words[:-1]
            compound_markers = {"and", "then", "with", "change", "configure", "set", "find"}
            web_markers = {"website", "webpage", "url", "link", "site", "tab", "folder", "file", "page"}
            if (
                target_words
                and len(target_words) <= 6
                and not (set(target_words) & compound_markers)
                and not (set(target_words) & web_markers)
            ):
                target = " ".join(target_words)
                if target == "setting":
                    target = "settings"
                return GoalClassification(
                    GoalCategory.OPEN_APP, 0.9, (target, ""),
                    "Search Windows for the requested application and invoke its named result.",
                )

        if len(words) >= 2 and words[0] in {"click", "tap"}:
            target_words = words[1:]
            if target_words and target_words[0] == "the":
                target_words = target_words[1:]
            if "copilot" in target_words and ("icon" in target_words or "button" in target_words):
                return GoalClassification(
                    GoalCategory.OPEN_APP, 0.9, ("copilot", ""),
                    "Search Windows for Copilot and invoke its named result.",
                )
        return GoalClassification(
            GoalCategory.GENERAL, 0.0, None,
            "No deterministic specialized route matched; use the existing FSM.",
        )

    @staticmethod
    def _is_chat_question(goal: str) -> bool:
        normalized = goal.strip().casefold()
        if not normalized:
            return False
        # Explicit action requests remain desktop tasks even when phrased as questions.
        if re.search(r"\b(open|launch|start|run|click|tap|type|write|press)\b", normalized):
            return False
        english_prefixes = (
            "what ", "who ", "where ", "when ", "why ", "how ",
            "is ", "are ", "do ", "does ", "did ", "can ",
        )
        vietnamese_markers = (" là gì", " ở đâu", " tại sao", " như thế nào", "là ai")
        return (
            normalized.startswith(english_prefixes)
            or "?" in normalized
            or any(marker in normalized for marker in vietnamese_markers)
        )

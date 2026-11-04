"""Select a compact set of text-bearing UI elements relevant to a goal."""

import re
import unicodedata
from typing import Iterable, List

from agent.vision.parser import UIElement


class TextTargetSelector:
    """Rank OCR/UIA text elements locally so the LLM sees only useful candidates."""

    _COMMAND_WORDS = {
        "open", "launch", "start", "run", "click", "tap", "press", "select",
        "find", "look", "for", "the", "a", "an", "on", "in", "at", "to",
        "and", "then", "button", "text", "screen", "please", "can", "you",
    }

    @staticmethod
    def _normalize(value: str) -> str:
        folded = unicodedata.normalize("NFKD", value).casefold()
        plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
        return " ".join(re.findall(r"[a-z0-9]+", plain))

    def select(
        self,
        goal: str,
        elements: Iterable[UIElement],
        current_task: str = "",
        limit: int = 12,
    ) -> List[UIElement]:
        query = self._normalize(current_task or goal)
        terms = set(query.split()) - self._COMMAND_WORDS
        items = list(elements)
        if not items:
            return []
        if not terms:
            return items[:limit]

        ranked = []
        for index, element in enumerate(items):
            label = self._normalize(element.text)
            label_terms = set(label.split())
            overlap = len(terms & label_terms)
            exact_phrase = bool(label and label in query)
            if exact_phrase or overlap:
                score = (2.0 if exact_phrase else 0.0) + overlap / max(1, len(terms))
                ranked.append((score, index, element))

        if not ranked:
            return items[:limit]
        ranked.sort(key=lambda row: (-row[0], row[1]))
        return [element for _score, _index, element in ranked[:limit]]

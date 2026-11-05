"""
BrainClient providing prompt structuring, JSON schema enforcement, and action synthesis.
Works with any configured LLM provider (Gemini, Ollama, etc.).
"""

import json
import re
from typing import Any, Dict, List, Optional
from agent.llm.base import BaseLLMProvider, LLMResponse
from agent.logger import logger
from agent.brain.structural_analysis import StructuralAnalysisResult, analyze_file_structure
from agent.vision.base import BaseOCRProcessor


SYSTEM_PROMPT = """You are an autonomous local AI desktop agent controlling a personal computer.
Your job is to observe the screen, consider the user's goal, and output the single best next action in strict JSON.

Supported actions:
- click: {"element_id": str} for a listed target
- double_click: {"element_id": str} for a listed target
- right_click: {"element_id": str} for a listed target
- move/drag: use only when an explicit registered target supplies the coordinates through a local action workflow
- scroll: {"clicks": int}
- write: {"text": str, "interval": float}
- press: {"key": str} (e.g. "enter", "tab", "esc", "win")
- hotkey: {"keys": [str, ...]} (e.g. ["ctrl", "c"], ["win", "r"])
- wait: {"seconds": float}
- launch_app: {"app_name": str} (e.g. "chrome", "code", "notepad")
- kill_app: {"process_name": str}
- read_file: {"path": str}
- write_file: {"path": str, "content": str}

Output MUST be valid JSON with this exact schema:
{
  "thought": "Your internal step-by-step reasoning about the screen state",
  "reason": "Why this specific action is the best next step",
  "action": "action_name",
  "params": {}
}
Do NOT include markdown fences, preambles, or explanations outside the JSON object.
When a matching UI element is listed, select it by its exact element_id instead of guessing coordinates. Never invent x/y coordinates or output bounding boxes. The local coordinate registry resolves the selected current-frame element ID to coordinates.
"""


class BrainClient:
    """Client for agent reasoning brain using the LLM provider abstraction."""

    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider

    def analyze_file_structure(
        self,
        elements: List[Any],
        *,
        file_id: Optional[str] = None,
        expected_headers: Optional[List[str]] = None,
    ) -> StructuralAnalysisResult:
        """Analyze one OCR result locally without invoking the LLM provider."""
        return analyze_file_structure(
            elements,
            file_id=file_id,
            expected_headers=expected_headers,
        )

    def analyze_ocr_result(
        self,
        ocr_result: Dict[str, Any],
        *,
        file_id: Optional[str] = None,
        expected_headers: Optional[List[str]] = None,
    ) -> StructuralAnalysisResult:
        """Analyze a single OCR payload without invoking the reasoning provider."""
        return self.analyze_file_structure(
            ocr_result.get("elements", []),
            file_id=file_id,
            expected_headers=expected_headers,
        )

    def analyze_screen(
        self,
        image: Any,
        ocr_processor: BaseOCRProcessor,
        *,
        file_id: Optional[str] = None,
        expected_headers: Optional[List[str]] = None,
    ) -> StructuralAnalysisResult:
        """Run the supplied OCR processor, then analyze this screen independently."""
        ocr_result = ocr_processor.extract_text(image)
        return self.analyze_ocr_result(
            ocr_result,
            file_id=file_id,
            expected_headers=expected_headers,
        )

    def analyze_files_independently(
        self,
        ocr_results: Dict[str, Dict[str, Any]],
        *,
        expected_headers: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, StructuralAnalysisResult]:
        """Analyze multiple visible files independently in one observation.

        The returned contexts are keyed by file id and are never reused between
        files. Any later comparison is intentionally left to an audit layer.
        """
        return {
            file_id: self.analyze_ocr_result(
                result,
                file_id=file_id,
                expected_headers=(expected_headers or {}).get(file_id),
            )
            for file_id, result in ocr_results.items()
        }

    def _build_prompt(
        self,
        goal: str,
        screen_text: str,
        memories: List[str],
        previous_actions: List[Dict[str, Any]],
        current_task: Optional[str] = None,
        ui_elements: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Format the 4 prompt sections specified in TDD Section 6."""
        memories_str = "\n".join(f"- {m}" for m in memories) if memories else "None."
        actions_str = "\n".join(
            f"- {a.get('action')}: {a.get('status')} ({a.get('result_message')})"
            for a in previous_actions
        ) if previous_actions else "None."
        ui_elements_str = "\n".join(
            f"- id={item.get('element_id')} type={item.get('control_type') or 'text'} "
            f"label={item.get('text')!r} surface={item.get('surface', 'desktop')} "
            f"container={item.get('container_id')} window={item.get('window_title')!r} "
            f"source={item.get('source')}"
            for item in (ui_elements or [])[:60]
        ) or "None."

        prompt = f"""=== 1. USER GOAL ===
{goal}
Active Sub-task: {current_task or 'In progress'}

=== 2. CURRENT SCREEN (OCR TEXT) ===
{screen_text if screen_text.strip() else "[Empty or no text visible]"}

=== 2B. ACCESSIBLE UI ELEMENTS (SELECT BY ID) ===
{ui_elements_str}

=== 3. RELEVANT MEMORIES & LESSONS ===
{memories_str}

=== 4. PREVIOUS ACTIONS ===
{actions_str}

Output JSON action:"""
        return prompt

    def _extract_json(self, raw_text: str) -> Dict[str, Any]:
        """Extract and parse JSON object even if enclosed in markdown code fences."""
        cleaned = raw_text.strip()
        # Remove markdown code block markers
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()

        # Find first '{' and last '}'
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            json_substr = cleaned[start : end + 1]
            return json.loads(json_substr)

        raise ValueError(f"No JSON object found in response: {raw_text[:200]}")

    async def generate_action(
        self,
        goal: str,
        screen_text: str,
        memories: Optional[List[str]] = None,
        previous_actions: Optional[List[Dict[str, Any]]] = None,
        current_task: Optional[str] = None,
        ui_elements: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Query brain for the next desktop action."""
        prompt = self._build_prompt(
            goal=goal,
            screen_text=screen_text,
            memories=memories or [],
            previous_actions=previous_actions or [],
            current_task=current_task,
            ui_elements=ui_elements or [],
        )

        raw = await self.provider.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            json_mode=True,
        )

        try:
            parsed = self._extract_json(raw)
            return LLMResponse(
                content=raw,
                thought=parsed.get("thought", ""),
                reason=parsed.get("reason", ""),
                action=parsed.get("action", "wait"),
                params=parsed.get("params", {}),
                raw_response=raw,
            )
        except Exception as e:
            logger.warning(f"[BrainClient] JSON parse error: {e}, raw was: {raw[:150]}")
            # Safe fallback action
            return LLMResponse(
                content=raw,
                thought="Failed to parse model JSON output, waiting to re-evaluate screen.",
                reason="Recovery step due to model JSON syntax error.",
                action="wait",
                params={"seconds": 1.0},
                raw_response=raw,
            )

    async def evaluate_result(self, goal: str, screen_text: str, action: str) -> bool:
        """Evaluate whether an action achieved its intended screen change."""
        prompt = f"""Goal: {goal}
Action performed: {action}
New screen text: {screen_text[:1000]}

Did this action make progress towards the goal? Reply strictly 'YES' or 'NO'."""
        res = await self.provider.generate(prompt=prompt, json_mode=False)
        return "YES" in res.upper()


# Backward-compatibility alias
QwenClient = BrainClient

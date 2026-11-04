"""Allow-list registry: models can select registered work only."""

import json
from pathlib import Path
from typing import Dict, Iterable, Optional

from agent.workflows.models import WorkflowSpec


class WorkflowRegistry:
    def __init__(self, specs: Optional[Iterable[WorkflowSpec]] = None, approved_path: Optional[Path] = None):
        self._specs: Dict[str, WorkflowSpec] = {}
        self.approved_path = approved_path or Path(__file__).resolve().parents[2] / "training_data" / "approved_workflows.json"
        for spec in specs or self.default_specs():
            self.register(spec)
        self._load_approved()

    @staticmethod
    def default_specs() -> tuple[WorkflowSpec, ...]:
        return (
            WorkflowSpec("CHAT", "Answer a conversational question without claiming desktop actions.", ("message",), ("language",), handler="chat", chainable=False),
            WorkflowSpec("OPEN_APP", "Open a desktop application and verify launch.", ("app_name",), handler="open_app"),
            WorkflowSpec("WRITE_TEXT_TO_APP", "Generate requested text and stream it into one verified foreground application window.", ("target_app", "instruction"), ("window_title",), handler="write_text_to_app", chainable=False),
            WorkflowSpec("WEB_SEARCH", "Open a Google search for a query in the default browser.", ("query",), handler="web_search"),
            WorkflowSpec("GENERATE_TEXT", "Draft or transform text requested by the user.", ("instruction",), ("context",), handler="generate_text"),
            WorkflowSpec("READ_SCREEN", "Read visible on-screen text using the configured OCR module.", (), handler="read_screen", chainable=False),
            WorkflowSpec("FSM_TASK", "Delegate a complex multi-step desktop task to the existing FSM and planner.", ("goal",), handler="fsm_task", chainable=False),
            WorkflowSpec("WORKFLOW_CHAIN", "Run a short ordered sequence of registered workflows.", ("steps",), handler="chain", chainable=False),
        )

    def register(self, spec: WorkflowSpec) -> None:
        key = spec.name.strip().upper()
        if not key or not key.replace("_", "").isalnum():
            raise ValueError("Workflow names must be uppercase identifier-like values.")
        self._specs[key] = spec

    def get(self, name: str) -> Optional[WorkflowSpec]:
        return self._specs.get(name.strip().upper())

    def list_specs(self) -> tuple[WorkflowSpec, ...]:
        return tuple(self._specs.values())

    def descriptions(self) -> str:
        return "\n".join(f"- {s.name}: {s.description} Parameters: required={list(s.required)}, optional={list(s.optional)}" for s in self.list_specs())

    def _load_approved(self) -> None:
        if not self.approved_path.exists():
            return
        try:
            data = json.loads(self.approved_path.read_text(encoding="utf-8"))
            for item in data.get("workflows", []):
                steps = item.get("steps", [])
                if not isinstance(steps, list) or not steps:
                    continue
                # Approved composites can only call existing concrete handlers.
                valid = all(self.get(step.get("workflow", "")) and self.get(step.get("workflow", "")).handler != "chain" for step in steps)
                if valid:
                    name = str(item["name"]).upper()
                    self.register(WorkflowSpec(name, str(item.get("description", "Approved composite workflow.")), ("parameters",), ("message",), handler="approved_chain"))
        except (OSError, ValueError, KeyError, TypeError):
            # A damaged optional registry must not prevent application startup.
            return

    def approved_definition(self, name: str) -> Optional[dict]:
        if not self.approved_path.exists():
            return None
        try:
            items = json.loads(self.approved_path.read_text(encoding="utf-8")).get("workflows", [])
            return next((x for x in items if str(x.get("name", "")).upper() == name.upper()), None)
        except (OSError, ValueError, TypeError):
            return None

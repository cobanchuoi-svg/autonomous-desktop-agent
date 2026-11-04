"""Creates workflow candidates; only explicit approval adds a composite to registry."""

import json
import re
from pathlib import Path
from typing import Any, Dict

from agent.workflows.registry import WorkflowRegistry


class WorkflowDesigner:
    def __init__(self, provider: Any, registry: WorkflowRegistry, candidate_dir: Path | None = None):
        self.provider = provider
        self.registry = registry
        self.candidate_dir = candidate_dir or Path(__file__).resolve().parents[2] / "training_data" / "workflow_candidates"

    async def propose(self, request: str) -> Dict[str, Any]:
        allowed = [s.name for s in self.registry.list_specs() if s.handler not in ("chain", "approved_chain")]
        prompt = f"Propose a reusable composite workflow for this request using only these workflow IDs: {allowed}. Return JSON {{\"name\":\"UPPER_SNAKE_CASE\",\"description\":\"...\",\"steps\":[{{\"workflow\":\"ID\",\"parameters\":{{}}}}]}}. No tools, code, or unregistered IDs. Request: {request}"
        raw = await self.provider.generate(prompt, system_prompt="You draft workflow candidates only. Never claim they are approved or executed.", json_mode=True)
        item = json.loads(raw)
        self._validate_candidate(item)
        item["status"] = "pending_approval"
        self.candidate_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "_", item["name"].lower()).strip("_")
        path = self.candidate_dir / f"{slug}.json"
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"candidate_id": slug, **item, "path": str(path)}

    def approve(self, candidate_id: str) -> Dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9_]{1,64}", candidate_id):
            raise ValueError("Candidate ID has invalid characters.")
        path = self.candidate_dir / f"{candidate_id}.json"
        item = json.loads(path.read_text(encoding="utf-8"))
        self._validate_candidate(item)
        approved_path = self.registry.approved_path
        approved_path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(approved_path.read_text(encoding="utf-8")) if approved_path.exists() else {"workflows": []}
        if any(str(x.get("name", "")).upper() == item["name"].upper() for x in data["workflows"]):
            raise ValueError(f"Workflow '{item['name']}' is already approved.")
        approved = {k: item[k] for k in ("name", "description", "steps")}
        data["workflows"].append(approved)
        approved_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        item["status"] = "approved"
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        self.registry._load_approved()
        return approved

    def _validate_candidate(self, item: Any) -> None:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("steps"), list):
            raise ValueError("Candidate must contain a name and steps array.")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", item["name"].upper()):
            raise ValueError("Candidate name must be an identifier of 2 to 64 characters.")
        if self.registry.get(item["name"]):
            raise ValueError(f"Workflow '{item['name']}' is already registered.")
        if not 1 <= len(item["steps"]) <= 5:
            raise ValueError("Candidates must have 1 to 5 steps.")
        for index, step in enumerate(item["steps"]):
            if not isinstance(step, dict) or set(step) - {"workflow", "parameters"}:
                raise ValueError(f"Step {index + 1} has invalid fields.")
            spec = self.registry.get(str(step.get("workflow", "")))
            if not spec or spec.handler in ("chain", "approved_chain") or not spec.chainable:
                raise ValueError(f"Step {index + 1} references an unavailable workflow.")
            spec.validate_parameters(step.get("parameters", {}))

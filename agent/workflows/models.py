"""Typed contracts for routing and executing registered workflows."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class WorkflowRequest:
    workflow: str
    confidence: float
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: str = "MATCH"
    clarification_question: Optional[str] = None
    router_source: str = "llm"
    fallback_error: Optional[str] = None


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    description: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    handler: Optional[str] = None
    chainable: bool = True

    def validate_parameters(self, parameters: Dict[str, Any]) -> None:
        if not isinstance(parameters, dict):
            raise ValueError(f"Parameters for {self.name} must be a JSON object.")
        missing = [
            name for name in self.required
            if name not in parameters
            or parameters[name] is None
            or (isinstance(parameters[name], str) and not parameters[name].strip())
        ]
        unknown = sorted(set(parameters) - set(self.required) - set(self.optional))
        if missing:
            raise ValueError(f"{self.name} is missing required parameters: {', '.join(missing)}")
        if unknown:
            raise ValueError(f"{self.name} received unsupported parameters: {', '.join(unknown)}")


@dataclass
class WorkflowResult:
    workflow: str
    success: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

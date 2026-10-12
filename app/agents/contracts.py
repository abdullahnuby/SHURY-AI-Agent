from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AgentStatus = Literal["success", "partial", "blocked", "needs_input", "failed", "timeout"]


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    name: str
    capability: str
    description: str = ""
    allowed_tools: tuple[str, ...] = ()
    read_only: bool = True
    max_timeout_seconds: float = 30.0
    resource_budget: dict[str, float] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.agent_id or not str(self.agent_id).strip():
            errors.append("agent_id is required")
        if not self.name or not str(self.name).strip():
            errors.append("name is required")
        if not self.capability or not str(self.capability).strip():
            errors.append("capability is required")
        if self.max_timeout_seconds <= 0:
            errors.append("max_timeout_seconds must be > 0")
        for tool in self.allowed_tools:
            if not str(tool).strip():
                errors.append("allowed_tools cannot contain empty names")
                break
        return errors


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    objective: str
    capability: str
    inputs: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()
    success_conditions: tuple[str, ...] = ()
    authority_scope: tuple[str, ...] = ()
    timeout_seconds: float = 30.0

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.task_id or not str(self.task_id).strip():
            errors.append("task_id is required")
        if not self.objective or not str(self.objective).strip():
            errors.append("objective is required")
        if not self.capability or not str(self.capability).strip():
            errors.append("capability is required")
        if self.timeout_seconds <= 0:
            errors.append("timeout_seconds must be > 0")
        if not isinstance(self.inputs, dict):
            errors.append("inputs must be a dict")
        seen: set[str] = set()
        for dep in self.dependencies:
            if not str(dep).strip():
                errors.append("dependency ids cannot be empty")
                continue
            if dep in seen:
                errors.append(f"duplicate dependency id: {dep}")
            seen.add(dep)
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "capability": self.capability,
            "inputs": dict(self.inputs),
            "dependencies": list(self.dependencies),
            "success_conditions": list(self.success_conditions),
            "authority_scope": list(self.authority_scope),
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class AgentResult:
    task_id: str
    status: AgentStatus
    output: Any = None
    evidence: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    VALID_STATUSES = {"success", "partial", "blocked", "needs_input", "failed", "timeout"}

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.task_id or not str(self.task_id).strip():
            errors.append("task_id is required")
        if self.status not in self.VALID_STATUSES:
            errors.append(f"status '{self.status}' is not valid")
        if not isinstance(self.evidence, (tuple, list)):
            errors.append("evidence must be a tuple/list of strings")
        if not isinstance(self.errors, (tuple, list)):
            errors.append("errors must be a tuple/list of strings")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "output": self.output,
            "evidence": list(self.evidence),
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }

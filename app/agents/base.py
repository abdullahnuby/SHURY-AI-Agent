from __future__ import annotations

from abc import ABC, abstractmethod

from .contracts import AgentResult, AgentSpec, AgentTask


class SpecialistAgent(ABC):
    """Minimal specialist protocol for bounded, capability-scoped execution."""

    def __init__(self, spec: AgentSpec | dict):
        if isinstance(spec, dict):
            spec = AgentSpec(
                agent_id=str(spec.get("agent_id", "")),
                name=str(spec.get("name", "")),
                capability=str(spec.get("capability", "")),
                description=str(spec.get("description", "")),
                allowed_tools=tuple(str(item) for item in spec.get("allowed_tools", ()) or ()),
                read_only=bool(spec.get("read_only", True)),
                max_timeout_seconds=float(spec.get("max_timeout_seconds", 30.0)),
                resource_budget=dict(spec.get("resource_budget", {}) or {}),
            )
        errors = spec.validate()
        if errors:
            raise ValueError("; ".join(errors))
        self.spec = spec

    @property
    def agent_id(self) -> str:
        return self.spec.agent_id

    def can_handle(self, task: AgentTask) -> bool:
        if task.capability not in {self.spec.capability, *self.spec.allowed_tools}:
            return False
        return True

    @abstractmethod
    def run(self, task: AgentTask) -> AgentResult:
        raise NotImplementedError

    def validate_result(self, result: AgentResult) -> list[str]:
        return result.validate()

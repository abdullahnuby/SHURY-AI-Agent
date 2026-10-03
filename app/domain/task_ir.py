"""Typed intermediate representation for deterministic SHURY task planning."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskCondition:
    kind: str
    expression: str
    consequence: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class TaskNode:
    id: str
    objective: str
    planner_goal: str = ""
    kind: str = "action"
    intent: str = ""
    capability: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    relation: str = "root"
    success_conditions: tuple[str, ...] = ()
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "objective": self.objective,
            "planner_goal": self.planner_goal,
            "kind": self.kind,
            "intent": self.intent,
            "capability": self.capability,
            "arguments": dict(self.arguments),
            "depends_on": list(self.depends_on),
            "relation": self.relation,
            "success_conditions": list(self.success_conditions),
            "confidence": round(max(0.0, min(1.0, float(self.confidence))), 3),
        }


@dataclass
class TaskIR:
    original: str
    objective: str
    nodes: list[TaskNode] = field(default_factory=list)
    conditions: list[TaskCondition] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    planner_goal: str = ""
    confidence: float = 0.0

    @property
    def compound(self) -> bool:
        return len(self.nodes) > 1 or bool(self.conditions)

    @property
    def executable(self) -> bool:
        if not self.nodes or self.unresolved or self.conditions:
            return False
        return all(bool(n.objective.strip()) and bool(n.planner_goal.strip() or n.capability.strip()) for n in self.nodes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "objective": self.objective,
            "nodes": [n.to_dict() for n in self.nodes],
            "conditions": [c.to_dict() for c in self.conditions],
            "constraints": dict(self.constraints),
            "assumptions": list(self.assumptions),
            "unresolved": list(self.unresolved),
            "planner_goal": self.planner_goal,
            "confidence": round(max(0.0, min(1.0, float(self.confidence))), 3),
            "compound": self.compound,
            "executable": self.executable,
        }

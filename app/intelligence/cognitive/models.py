from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass(frozen=True)
class Hypothesis:
    statement: str
    evidence_needed: list[str] = field(default_factory=list)
    confidence: float = 0.0
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class CognitiveBrief:
    goal: str
    task_type: str
    success_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    subgoals: list[str] = field(default_factory=list)
    information_gaps: list[str] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    strategy: str = "hybrid"
    risk: str = "low"
    confidence: float = 0.0
    needs_clarification: bool = False
    clarification_question: str = ""
    first_action_hint: str = ""
    baseline_plan: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "deterministic"
    def to_dict(self) -> dict[str, Any]:
        return {
            **{k: v for k, v in asdict(self).items() if k != "hypotheses"},
            "hypotheses": [h.to_dict() for h in self.hypotheses],
        }

@dataclass
class CognitiveReflection:
    progress: float = 0.0
    goal_status: str = "progressing"
    new_facts: list[str] = field(default_factory=list)
    changed_assumptions: list[str] = field(default_factory=list)
    information_gaps: list[str] = field(default_factory=list)
    failure_class: str = ""
    should_replan: bool = False
    next_objective: str = ""
    rationale_summary: str = ""
    confidence: float = 0.0
    mode: str = "deterministic"
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

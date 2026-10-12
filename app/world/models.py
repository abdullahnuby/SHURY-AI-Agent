from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EntityState:
    entity_id: str
    kind: str = "entity"
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    status: str = "active"


@dataclass(frozen=True)
class RelationState:
    relation_id: str
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    status: str = "active"


@dataclass(frozen=True)
class StateDiff:
    added_facts: tuple[str, ...] = ()
    removed_facts: tuple[str, ...] = ()
    added_capabilities: tuple[str, ...] = ()
    removed_capabilities: tuple[str, ...] = ()
    changed_variables: tuple[str, ...] = ()
    changed_resources: tuple[str, ...] = ()
    added_entities: tuple[str, ...] = ()
    removed_entities: tuple[str, ...] = ()
    added_relations: tuple[str, ...] = ()
    removed_relations: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return any((
            self.added_facts, self.removed_facts, self.added_capabilities, self.removed_capabilities, self.changed_variables,
            self.changed_resources, self.added_entities, self.removed_entities,
            self.added_relations, self.removed_relations,
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "added_facts": list(self.added_facts),
            "removed_facts": list(self.removed_facts),
            "added_capabilities": list(self.added_capabilities),
            "removed_capabilities": list(self.removed_capabilities),
            "changed_variables": list(self.changed_variables),
            "changed_resources": list(self.changed_resources),
            "added_entities": list(self.added_entities),
            "removed_entities": list(self.removed_entities),
            "added_relations": list(self.added_relations),
            "removed_relations": list(self.removed_relations),
            "changed": self.changed,
        }


@dataclass(frozen=True)
class Observation:
    observation_id: str
    timestamp: str
    source: str
    action: str
    ok: bool
    verified: bool
    summary: str
    raw_output: Any = None
    error: str | None = None
    state_diff: StateDiff = field(default_factory=StateDiff)
    confidence: float = 1.0
    tainted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "action": self.action,
            "ok": self.ok,
            "verified": self.verified,
            "summary": self.summary,
            "raw_output": self.raw_output,
            "error": self.error,
            "state_diff": self.state_diff.to_dict(),
            "confidence": self.confidence,
            "tainted": self.tainted,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class PredictedTransition:
    action: str
    expected_changes: StateDiff = field(default_factory=StateDiff)
    predicted_state: str | None = None
    confidence: float = 1.0
    reversible: bool = True
    risk: str = "low"
    rationale: str = ""
    source: str = "deterministic"
    warnings: tuple[str, ...] = ()
    prediction_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "expected_changes": self.expected_changes.to_dict(),
            "predicted_state": self.predicted_state,
            "confidence": self.confidence,
            "reversible": self.reversible,
            "risk": self.risk,
            "rationale": self.rationale,
            "source": self.source,
            "warnings": list(self.warnings),
            "prediction_details": self.prediction_details,
        }


@dataclass(frozen=True)
class WorldAssessment:
    consistent: bool
    confidence: float
    stale: bool
    unresolved: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "consistent": self.consistent,
            "confidence": self.confidence,
            "stale": self.stale,
            "unresolved": list(self.unresolved),
            "risks": list(self.risks),
            "rationale": self.rationale,
        }

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class EntityMention:
    text: str
    type: str
    normalized: str
    confidence: float = 0.0
    start: int = -1
    end: int = -1
    source: str = "deterministic"
    canonical: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["confidence"] = round(_clamp(self.confidence), 3)
        return d


@dataclass(frozen=True)
class IntentCandidate:
    name: str
    confidence: float
    evidence: tuple[str, ...] = ()
    capability: str = ""
    required_slots: tuple[str, ...] = ()
    missing_slots: tuple[str, ...] = ()
    source: str = "hybrid"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["confidence"] = round(_clamp(self.confidence), 3)
        d["evidence"] = list(self.evidence)
        d["required_slots"] = list(self.required_slots)
        d["missing_slots"] = list(self.missing_slots)
        return d


@dataclass(frozen=True)
class Reference:
    text: str
    kind: str
    target: str = ""
    resolved: bool = False
    confidence: float = 0.0
    source: str = "deterministic"
    basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["confidence"] = round(_clamp(self.confidence), 3)
        return d


@dataclass(frozen=True)
class TemporalExpression:
    text: str
    kind: str
    start: str = ""
    end: str = ""
    granularity: str = ""
    timezone: str = "Africa/Cairo"
    confidence: float = 0.0
    source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["confidence"] = round(_clamp(self.confidence), 3)
        return d


@dataclass(frozen=True)
class SemanticConstraint:
    key: str
    operator: str
    value: str
    confidence: float = 0.0
    source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["confidence"] = round(_clamp(self.confidence), 3)
        return d


@dataclass
class SemanticParse:
    original: str
    normalized: str
    language: str
    language_variant: str = "unknown"
    domain: str = "general"
    canonical_goal: str = ""
    intent_candidates: list[IntentCandidate] = field(default_factory=list)
    entities: list[EntityMention] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    temporal: list[TemporalExpression] = field(default_factory=list)
    constraints: list[SemanticConstraint] = field(default_factory=list)
    slots: dict[str, str] = field(default_factory=dict)
    required_information: list[str] = field(default_factory=list)
    ambiguity_reasons: list[str] = field(default_factory=list)
    safety_signals: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str = ""
    confidence: float = 0.0
    speech_act: str = "request"
    actionability: str = "action"
    requires_fresh_data: bool = False
    source: str = "deterministic"
    memory_need: str = "none"
    memory_types: tuple[str, ...] = ()
    memory_reason: str = ""

    @property
    def top_intent(self) -> IntentCandidate | None:
        return self.intent_candidates[0] if self.intent_candidates else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "normalized": self.normalized,
            "language": self.language,
            "language_variant": self.language_variant,
            "domain": self.domain,
            "canonical_goal": self.canonical_goal,
            "intent_candidates": [x.to_dict() for x in self.intent_candidates],
            "entities": [x.to_dict() for x in self.entities],
            "references": [x.to_dict() for x in self.references],
            "temporal": [x.to_dict() for x in self.temporal],
            "constraints": [x.to_dict() for x in self.constraints],
            "slots": dict(self.slots),
            "required_information": list(self.required_information),
            "ambiguity_reasons": list(self.ambiguity_reasons),
            "safety_signals": list(self.safety_signals),
            "needs_clarification": bool(self.needs_clarification),
            "clarification_question": self.clarification_question,
            "confidence": round(_clamp(self.confidence), 3),
            "speech_act": self.speech_act,
            "actionability": self.actionability,
            "requires_fresh_data": bool(self.requires_fresh_data),
            "source": self.source,
            "memory_need": self.memory_need,
            "memory_types": list(self.memory_types),
            "memory_reason": self.memory_reason,
        }

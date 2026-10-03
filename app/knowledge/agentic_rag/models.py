from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass(frozen=True)
class SubQuestion:
    id: str
    question: str
    purpose: str = "answer"
    route: str = "local"  # local | web | hybrid
    required: bool = True
    status: str = "open"
    queries: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class ResearchPlan:
    query: str
    route: str
    subquestions: list[SubQuestion] = field(default_factory=list)
    max_rounds: int = 3
    max_evidence: int = 24
    rationale: list[str] = field(default_factory=list)
    source_preferences: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "route": self.route,
            "subquestions": [x.to_dict() for x in self.subquestions],
            "max_rounds": self.max_rounds,
            "max_evidence": self.max_evidence,
            "rationale": list(self.rationale),
            "source_preferences": list(self.source_preferences),
        }

@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    source_kind: str
    title: str
    url: str
    text: str
    query: str
    rank: int = 0
    relevance: float = 0.0
    authority: float = 0.0
    freshness: float = 0.0
    diversity: float = 0.0
    indexed: bool = False
    content_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def quality(self) -> float:
        return round(0.48 * self.relevance + 0.24 * self.authority + 0.16 * self.freshness + 0.12 * self.diversity, 6)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["quality"] = self.quality
        return payload

@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    support_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    verification: str = "unverified"  # supported | conflicting | dropped | unverified
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class AgenticRAGResult:
    query: str
    outcome: str  # answered | partial | abstained | clarify | budget
    answer: str
    confidence: float
    plan: ResearchPlan
    evidence: list[EvidenceItem] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    synthesis_mode: str = "extractive"
    verification: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "outcome": self.outcome,
            "answer": self.answer,
            "confidence": self.confidence,
            "plan": self.plan.to_dict(),
            "evidence": [x.to_dict() for x in self.evidence],
            "claims": [x.to_dict() for x in self.claims],
            "trace": list(self.trace),
            "missing": list(self.missing),
            "conflicts": list(self.conflicts),
            "methods": list(self.methods),
            "synthesis_mode": self.synthesis_mode,
            "verification": dict(self.verification),
            "reason": self.reason,
        }

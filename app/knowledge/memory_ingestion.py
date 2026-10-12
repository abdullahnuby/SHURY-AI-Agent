"""Deterministic memory-ingestion pipeline for Phase 5.

The pipeline keeps interaction capture separate from durable-memory promotion:

RAW EPISODE -> CANDIDATE -> VALIDATION -> DEDUP/CONFLICT -> PROMOTION

Only explicit, high-confidence candidates can be promoted automatically. Ordinary
conversation remains episodic. Secrets are rejected before durable promotion.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.knowledge.memory_models import MemoryCandidate
from app.knowledge.memory_extraction import contains_secret_pattern, extract
from app.knowledge.memory_types import FACT, PREFERENCE, USER, contract_for

AUTO_PROMOTION_THRESHOLD = {
    FACT: 0.90,
    PREFERENCE: 0.90,
}


@dataclass(frozen=True)
class CandidateDecision:
    candidate: MemoryCandidate
    stage: str
    status: str
    reason: str
    conflict: bool = False
    existing_memory_id: int | None = None
    promoted_memory_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": asdict(self.candidate),
            "stage": self.stage,
            "status": self.status,
            "reason": self.reason,
            "conflict": self.conflict,
            "existing_memory_id": self.existing_memory_id,
            "promoted_memory_id": self.promoted_memory_id,
        }


@dataclass(frozen=True)
class MemoryIngestionResult:
    episode_id: int
    decisions: tuple[CandidateDecision, ...] = ()
    promoted: tuple[dict[str, Any], ...] = ()
    rejected: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def candidates(self) -> list[dict[str, Any]]:
        return [decision.to_dict() for decision in self.decisions]

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "candidates": self.candidates,
            "promoted": list(self.promoted),
            "rejected": list(self.rejected),
            "diagnostics": dict(self.diagnostics),
        }


class MemoryIngestionController:
    """Own only ingestion decisions; Memory remains the storage authority."""

    def __init__(self, memory: Any):
        self.memory = memory

    def ingest_user_turn(
        self,
        user_text: str,
        *,
        assistant_text: str = "",
        outcome: str | None = None,
        owner_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        metadata: dict | None = None,
        tool_events: list[dict] | tuple[dict, ...] | None = None,
        entities: list[dict] | tuple[dict, ...] | None = None,
        experience_kind: str = "interaction",
        auto_promote: bool = True,
    ) -> MemoryIngestionResult:
        """Record the raw episode, then validate and optionally promote candidates."""
        ctx = self.memory._resolve_memory_context(
            scope=USER, owner_id=owner_id, session_id=session_id, run_id=run_id
        )
        episode_id = self.memory.add_episode(
            user_text,
            assistant_text,
            outcome=outcome,
            owner_id=ctx["owner_id"],
            session_id=ctx["session_id"],
            run_id=ctx["run_id"],
            metadata=metadata,
            tool_events=tool_events,
            entities=entities,
            experience_kind=experience_kind,
        )

        text = str(user_text or "").strip()
        if not text:
            return MemoryIngestionResult(
                episode_id=episode_id,
                diagnostics={"raw_episode": True, "candidate_count": 0},
            )

        # Secret-bearing turns remain episodic but can never produce durable candidates.
        if contains_secret_pattern(text):
            return MemoryIngestionResult(
                episode_id=episode_id,
                decisions=(),
                rejected=({"stage": "candidate", "status": "rejected", "reason": "secret_material"},),
                diagnostics={"raw_episode": True, "secret_blocked": True, "candidate_count": 0},
            )

        candidates = extract(text)
        decisions: list[CandidateDecision] = []
        promoted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for candidate in candidates:
            decision = self._process_candidate(
                candidate,
                episode_id=episode_id,
                owner_id=ctx["owner_id"],
                session_id=ctx["session_id"],
                run_id=ctx["run_id"],
                auto_promote=auto_promote,
            )
            decisions.append(decision)
            if decision.promoted_memory_id is not None:
                promoted.append({
                    "id": decision.promoted_memory_id,
                    "kind": candidate.kind,
                    "key": candidate.key,
                    "value": candidate.value,
                    "confidence": candidate.confidence,
                    "status": "promoted",
                    "conflict": decision.conflict,
                })
            elif decision.status != "promoted":
                rejected.append(decision.to_dict())

        return MemoryIngestionResult(
            episode_id=episode_id,
            decisions=tuple(decisions),
            promoted=tuple(promoted),
            rejected=tuple(rejected),
            diagnostics={
                "raw_episode": True,
                "candidate_count": len(candidates),
                "promotion_count": len(promoted),
                "auto_promote": bool(auto_promote),
            },
        )

    def _process_candidate(
        self,
        candidate: MemoryCandidate,
        *,
        episode_id: int,
        owner_id: str,
        session_id: str | None,
        run_id: str | None,
        auto_promote: bool,
    ) -> CandidateDecision:
        validation_error = self._validate(candidate)
        if validation_error:
            return CandidateDecision(candidate, "validation", "rejected", validation_error)

        key = self.memory.canonical_key(candidate.key or "")
        active = self.memory.list_memories(
            kind=candidate.kind,
            scope=USER,
            owner_id=owner_id,
            limit=500,
        )
        same_key = [row for row in active if self.memory.canonical_key(str(row.get("key") or "")) == key]
        for row in same_key:
            if self.memory.canonical_key(str(row.get("value") or "")) == self.memory.canonical_key(candidate.value):
                return CandidateDecision(
                    candidate,
                    "deduplication",
                    "deduplicated",
                    "identical active memory already exists",
                    existing_memory_id=int(row["id"]),
                    promoted_memory_id=int(row["id"]),
                )

        conflict = bool(same_key)
        if not auto_promote:
            return CandidateDecision(
                candidate,
                "promotion",
                "candidate",
                "automatic promotion disabled",
                conflict=conflict,
            )

        try:
            memory_id = self.memory.add_memory_candidate(
                candidate,
                source_ref=f"episode:{episode_id}",
                scope=USER,
                owner_id=owner_id,
                session_id=session_id,
                run_id=run_id,
                reason="phase5_explicit_candidate",
            )
        except (ValueError, PermissionError) as exc:
            return CandidateDecision(candidate, "promotion", "rejected", str(exc), conflict=conflict)

        return CandidateDecision(
            candidate,
            "promotion",
            "promoted",
            "validated explicit candidate",
            conflict=conflict,
            promoted_memory_id=int(memory_id),
        )

    @staticmethod
    def _validate(candidate: MemoryCandidate) -> str | None:
        try:
            contract_for(candidate.kind)
        except ValueError as exc:
            return str(exc)

        if candidate.kind not in AUTO_PROMOTION_THRESHOLD:
            return f"automatic promotion is not allowed for memory type {candidate.kind!r}"
        if candidate.sensitivity == "secret":
            return "secret material cannot become a durable candidate"
        if contains_secret_pattern(candidate.value):
            return "candidate value matches secret-material policy"
        if not str(candidate.value or "").strip():
            return "candidate value is empty"
        if not str(candidate.key or "").strip():
            return "durable fact/preference candidate requires a canonical key"
        threshold = AUTO_PROMOTION_THRESHOLD[candidate.kind]
        if float(candidate.confidence) < threshold:
            return f"confidence {candidate.confidence:.3f} is below promotion threshold {threshold:.3f}"
        return None

"""Canonical memory controller boundary for Brain retrieval.

Phase 13 keeps SQLite/storage details below this module. Brain receives only a
structured evidence bundle derived from the semantic memory requirement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.brain.models import Evidence
from app.knowledge.memory_query import MemoryQueryPlan, plan_memory_query


@dataclass(frozen=True)
class MemoryEvidence:
    memory_type: str
    content: str
    confidence: float = 0.0
    relevance: float = 0.0
    source: str = "canonical_memory"
    reference: str = ""
    provenance: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_brain_evidence(self) -> Evidence:
        kind = "knowledge_memory" if self.memory_type == "knowledge" else "memory"
        reference = f"{self.memory_type}:{self.reference}" if self.reference else self.memory_type
        provenance = f"memory_type={self.memory_type};{self.provenance}" if self.provenance else f"memory_type={self.memory_type}"
        return Evidence(
            kind=kind,
            content=self.content,
            source=self.source,
            confidence=max(0.0, min(1.0, float(self.confidence))),
            reference=reference,
            provenance=provenance,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_type": self.memory_type,
            "content": self.content,
            "confidence": round(max(0.0, min(1.0, float(self.confidence))), 3),
            "relevance": round(float(self.relevance), 6),
            "source": self.source,
            "reference": self.reference,
            "provenance": self.provenance,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MemoryEvidenceBundle:
    requirement: MemoryQueryPlan
    evidence: tuple[MemoryEvidence, ...] = ()
    scope: str = ""
    selected_stores: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.evidence)

    def to_brain_evidence(self) -> list[Evidence]:
        return [item.to_brain_evidence() for item in self.evidence]

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_requirement": self.requirement.to_dict(),
            "scope": self.scope,
            "selected_stores": list(self.selected_stores),
            "count": self.count,
            "evidence": [item.to_dict() for item in self.evidence],
        }


class MemoryController:
    """The only retrieval boundary Brain needs to know about."""

    def __init__(self, memory):
        self.memory = memory

    @staticmethod
    def requirement_from(frame_or_contract: Any, *, query: str = "") -> MemoryQueryPlan:
        if frame_or_contract is not None:
            need = str(getattr(frame_or_contract, "memory_need", "") or "none")
            memory_types = tuple(str(x) for x in (getattr(frame_or_contract, "memory_types", ()) or ()))
            reason = str(getattr(frame_or_contract, "memory_reason", "") or "")
            intent = str(getattr(frame_or_contract, "requested_operation", "") or "")
            slots = {}
            if hasattr(frame_or_contract, "slots"):
                try:
                    slots = dict(frame_or_contract.slots)
                except Exception:
                    slots = {}
            derived = plan_memory_query(query, intent=intent or "memory_search", slots=slots)
            store_map = {
                "user_fact": ("durable_user_memory",),
                "episodic": ("episodic",),
                "working_context": ("working", "episodic"),
                "procedural_experience": ("procedural", "episodic"),
                "entity_relation": ("entity_graph",),
                "knowledge": ("knowledge",),
                "mixed_personal": ("durable_user_memory", "episodic"),
            }
            if need != "none" or memory_types:
                stores = store_map.get(need, derived.stores)
                return MemoryQueryPlan(
                    need or "none",
                    memory_types,
                    stores,
                    reason or derived.rationale,
                    float(getattr(frame_or_contract, "confidence", 1.0) or 1.0),
                )
        return plan_memory_query(query, intent="memory_search")

    @staticmethod
    def _text(value: Any, *, fallback: str = "") -> str:
        text = str(value or "").strip()
        return text or fallback

    def _from_memory_rows(self, rows: list[dict], memory_type: str | None = None) -> list[MemoryEvidence]:
        out: list[MemoryEvidence] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            kind = str(memory_type or row.get("kind") or "memory").strip().casefold()
            key = self._text(row.get("key"))
            value = self._text(row.get("value"))
            content = value if not key else f"{key} = {value}"
            if not content:
                content = self._text(row.get("content"), fallback=self._text(row.get("text")))
            if not content:
                continue
            out.append(
                MemoryEvidence(
                    memory_type=kind,
                    content=content,
                    confidence=float(row.get("confidence", 0.0) or 0.0),
                    relevance=float(row.get("score", 0.0) or 0.0),
                    source=self._text(row.get("source"), fallback="canonical_memory"),
                    reference=f"memory:{row.get('id')}" if row.get("id") is not None else "",
                    provenance=self._text(row.get("source_ref"), fallback=self._text(row.get("source"))),
                    metadata={
                        "importance": row.get("importance"),
                        "revision": row.get("revision"),
                        "status": row.get("status"),
                    },
                )
            )
        return out

    def _from_episodes(self, rows: list[dict]) -> list[MemoryEvidence]:
        out: list[MemoryEvidence] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            summary = self._text(row.get("summary"))
            user_text = self._text(row.get("user_message"))
            assistant_text = self._text(row.get("assistant_response"))
            content = summary or user_text
            if user_text and assistant_text and not summary:
                content = f"User: {user_text} | Assistant: {assistant_text}"
            if not content:
                continue
            out.append(
                MemoryEvidence(
                    memory_type="episode",
                    content=content,
                    confidence=min(1.0, max(0.0, 0.65 + float(row.get("score", 0.0) or 0.0) * 0.35)),
                    relevance=float(row.get("score", 0.0) or 0.0),
                    source="episodic_memory",
                    reference=f"episode:{row.get('episode_id')}" if row.get("episode_id") is not None else "",
                    provenance=f"episode:{row.get('episode_id')}" if row.get("episode_id") is not None else "",
                    metadata={
                        "outcome": row.get("outcome"),
                        "timestamp": row.get("timestamp"),
                        "experience_kind": row.get("experience_kind"),
                    },
                )
            )
        return out

    def _from_working(self, rows: list[dict]) -> list[MemoryEvidence]:
        out: list[MemoryEvidence] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            content = self._text(row.get("content"), fallback=self._text(row.get("text")))
            if not content:
                continue
            out.append(
                MemoryEvidence(
                    memory_type="working",
                    content=content,
                    confidence=0.8,
                    relevance=float(row.get("score", 0.0) or 0.0),
                    source="working_memory",
                    reference=f"working:{row.get('id')}" if row.get("id") is not None else "",
                    provenance="working_context",
                )
            )
        return out

    def _from_graph(self, rows: list[dict]) -> list[MemoryEvidence]:
        out: list[MemoryEvidence] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            subject = self._text(row.get("subject"))
            predicate = self._text(row.get("predicate"))
            obj = self._text(row.get("object"))
            content = " ".join(x for x in (subject, predicate, obj) if x)
            if not content:
                continue
            out.append(
                MemoryEvidence(
                    memory_type="relation",
                    content=content,
                    confidence=float(row.get("confidence", 0.0) or 0.0),
                    relevance=float(row.get("confidence", 0.0) or 0.0),
                    source="entity_relation_memory",
                    reference=f"relation:{row.get('id')}" if row.get("id") is not None else "",
                    provenance=f"memory:{row.get('source_memory_id')}" if row.get("source_memory_id") else "",
                    metadata={"valid_at": row.get("valid_at"), "invalid_at": row.get("invalid_at")},
                )
            )
        return out

    def retrieve(self, query: str, *, frame_or_contract: Any = None, owner_id: str | None = None,
                 session_id: str | None = None, run_id: str | None = None, limit: int = 8,
                 intent: str | None = None, key: str | None = None) -> MemoryEvidenceBundle:
        requirement = self.requirement_from(frame_or_contract, query=query)
        if frame_or_contract is None and intent:
            requirement = plan_memory_query(query, intent=intent)
        if requirement.need == "none" and not requirement.memory_types:
            return MemoryEvidenceBundle(requirement=requirement, evidence=(), scope="", selected_stores=requirement.stores)

        raw = self.memory.recall_context(
            query,
            limit=limit,
            owner_id=owner_id,
            session_id=session_id,
            run_id=run_id,
            memory_plan=requirement.to_dict(),
            intent=intent,
        )
        evidence: list[MemoryEvidence] = []

        requested = set(requirement.memory_types)
        if requested & {"fact", "preference", "note"}:
            evidence.extend(self._from_memory_rows(raw.get("semantic") or [], "fact"))
            evidence.extend(self._from_memory_rows(raw.get("notes") or [], "note"))
            # Specific fact/profile retrieval is resolved inside the controller boundary.
            if key and not evidence:
                value = self.memory.get_fact(key, owner_id=owner_id, session_id=session_id)
                if value is None:
                    for alias in self.memory.key_aliases(key):
                        value = self.memory.get_fact(alias, owner_id=owner_id, session_id=session_id)
                        if value is not None:
                            key = alias
                            break
                if value is not None:
                    evidence.append(MemoryEvidence(
                        memory_type="fact", content=f"{key} = {value}", confidence=1.0,
                        relevance=1.0, source="canonical_memory", reference=f"fact:{key}",
                        provenance="canonical_memory",
                    ))
            if key is None and not evidence:
                evidence.extend(
                    self._from_memory_rows(self.memory.profile(owner_id=owner_id, session_id=session_id, limit=limit), "fact")
                )

        if "episode" in requested:
            evidence.extend(self._from_episodes(raw.get("episodic") or []))
        if "procedural" in requested:
            evidence.extend(self._from_memory_rows(raw.get("procedural") or [], "procedural"))
        if "working" in requested:
            evidence.extend(self._from_working(raw.get("working") or []))
        if requested & {"entity", "relation"}:
            evidence.extend(self._from_graph(raw.get("graph") or []))
        if "knowledge" in requested:
            evidence.extend(self._from_memory_rows(raw.get("knowledge") or [], "knowledge"))
        evidence.sort(key=lambda item: (-float(item.relevance), -float(item.confidence), item.reference, item.content))
        scope_by_need = {
            "knowledge": "knowledge",
            "entity_relation": "user",
            "episodic": "session" if session_id else "user",
            "working_context": "session",
            "procedural_experience": "user",
            "user_fact": "user",
            "mixed_personal": "user",
        }
        return MemoryEvidenceBundle(
            requirement=requirement,
            evidence=tuple(evidence[:max(1, int(limit))]),
            scope=scope_by_need.get(requirement.need, ""),
            selected_stores=requirement.stores,
        )

    def retrieve_for_frame(self, frame: Any, *, owner_id: str | None = None,
                           session_id: str | None = None, run_id: str | None = None, limit: int = 8) -> MemoryEvidenceBundle:
        query = frame.slot("query") if hasattr(frame, "slot") else ""
        query = query or getattr(frame, "text", "")
        key = frame.slot("key") if hasattr(frame, "slot") else ""
        intent = getattr(frame, "requested_operation", None)
        return self.retrieve(
            query,
            frame_or_contract=frame,
            owner_id=owner_id,
            session_id=session_id,
            run_id=run_id,
            limit=limit,
            intent=intent,
            key=key or None,
        )

    def profile_evidence(self, *, owner_id: str | None = None, session_id: str | None = None, limit: int = 24) -> MemoryEvidenceBundle:
        plan = MemoryQueryPlan("user_fact", ("fact", "preference", "note"), ("durable_user_memory",), "Brain user-memory projection", 1.0)
        rows = self.memory.profile(owner_id=owner_id, limit=limit)
        return MemoryEvidenceBundle(
            requirement=plan,
            evidence=tuple(self._from_memory_rows(rows, "fact")),
            scope="user",
            selected_stores=plan.stores,
        )

    def write_fact(self, key: str, value: Any, *, owner_id: str | None = None, session_id: str | None = None) -> Any:
        return self.memory.set_fact(key, value, owner_id=owner_id, session_id=session_id)


__all__ = ["MemoryController", "MemoryEvidence", "MemoryEvidenceBundle"]

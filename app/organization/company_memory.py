from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Iterable

from app.knowledge.memory import get_memory
from app.knowledge.memory_types import COMPANY, COMPANY_MEMORY

DEFAULT_COMPANY_MEMORY_OWNER = os.getenv("SHURY_COMPANY_ID", "shury-company")


@dataclass(frozen=True)
class CompanyMemoryHit:
    memory_id: int
    category: str
    key: str
    value: str
    confidence: float
    importance: int
    source_ref: str | None
    metadata: dict[str, Any]
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.memory_id,
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "importance": self.importance,
            "source_ref": self.source_ref,
            "metadata": dict(self.metadata),
            "score": round(self.score, 4),
        }


class CompanyMemory:
    """Governed organizational memory backed by SHURY's canonical Memory store."""

    def __init__(self, memory=None, *, company_id: str = DEFAULT_COMPANY_MEMORY_OWNER):
        self.memory = memory or get_memory()
        self.company_id = str(company_id).strip() or DEFAULT_COMPANY_MEMORY_OWNER

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _stable_key(category: str, payload: Any) -> str:
        digest = hashlib.sha256(CompanyMemory._json(payload).encode("utf-8")).hexdigest()[:24]
        return f"{category}:{digest}"

    def _remember(self, *, category: str, key: str, value: str, confidence: float, importance: int,
                  verified: bool, source_ref: str | None = None, metadata: dict[str, Any] | None = None, project_id: str | None = None) -> int:
        md = {
            "category": category,
            "company_id": self.company_id,
            "verified": bool(verified),
            "memory_schema": "company.v2",
            "project_id": str(project_id or ""),
            **dict(metadata or {}),
        }
        return self.memory.remember(
            value, kind=COMPANY_MEMORY, key=key, scope=COMPANY, owner_id=self.company_id,
            source="system", source_ref=source_ref, confidence=confidence, importance=importance,
            metadata=md, reason=f"company:{category}",
        )

    def remember_decision(self, *, decision_key: str, decision: dict[str, Any],
                          evidence: Iterable[str] = (), run_id: str | None = None,
                          confidence: float = 0.9, project_id: str | None = None) -> int:
        evidence_list = list(evidence)
        payload = {"decision": decision, "evidence": evidence_list}
        return self._remember(category="decision", key=f"decision:{decision_key}", value=self._json(payload),
                              confidence=confidence, importance=5, verified=True,
                              source_ref=f"company-run:{run_id}" if run_id else None,
                              metadata={"run_id": run_id, "evidence": evidence_list}, project_id=project_id)

    def remember_ownership(self, *, subject: str, department: str, role: str,
                           skill: str = "", capability: str = "", tool: str = "",
                           evidence: Iterable[str] = (), project_id: str | None = None) -> int:
        evidence_list = list(evidence)
        payload = {"subject": subject, "department": department, "role": role,
                   "skill": skill, "capability": capability, "tool": tool}
        key = self._stable_key("ownership", payload)
        return self._remember(category="ownership", key=key, value=self._json(payload),
                              confidence=1.0, importance=4, verified=True,
                              metadata={"evidence": evidence_list, "ownership_subject": subject}, project_id=project_id)

    def remember_procedure(self, *, capability: str, skill: str, tool: str,
                           procedure: dict[str, Any], evidence: Iterable[str],
                           run_id: str | None = None, confidence: float = 0.9, project_id: str | None = None) -> int:
        evidence_list = list(evidence)
        if not evidence_list:
            raise ValueError("company procedure requires verification evidence")
        payload = {"capability": capability, "skill": skill, "tool": tool, "procedure": procedure}
        key = self._stable_key("procedure", payload)
        return self._remember(category="procedure", key=key, value=self._json(payload),
                              confidence=confidence, importance=4, verified=True,
                              source_ref=f"company-run:{run_id}" if run_id else None,
                              metadata={"evidence": evidence_list, "run_id": run_id}, project_id=project_id)

    def remember_failure_lesson(self, *, capability: str, failure_class: str,
                                lesson: dict[str, Any], evidence: Iterable[str],
                                run_id: str | None = None, confidence: float = 0.8, project_id: str | None = None) -> int:
        evidence_list = list(evidence)
        if not evidence_list:
            raise ValueError("company lesson requires verification evidence")
        payload = {"capability": capability, "failure_class": failure_class, "lesson": lesson}
        key = self._stable_key("lesson", payload)
        return self._remember(category="lesson", key=key, value=self._json(payload),
                              confidence=confidence, importance=4, verified=True,
                              source_ref=f"company-run:{run_id}" if run_id else None,
                              metadata={"evidence": evidence_list, "run_id": run_id}, project_id=project_id)

    def remember_review_finding(self, *, review_key: str, finding: dict[str, Any],
                                blocking: bool, evidence: Iterable[str],
                                run_id: str | None = None, project_id: str | None = None) -> int:
        evidence_list = list(evidence)
        payload = {"finding": finding, "blocking": bool(blocking), "evidence": evidence_list}
        return self._remember(category="review_finding", key=f"review:{review_key}", value=self._json(payload),
                              confidence=1.0, importance=5 if blocking else 3, verified=True,
                              source_ref=f"company-run:{run_id}" if run_id else None,
                              metadata={"evidence": evidence_list, "blocking": bool(blocking), "run_id": run_id}, project_id=project_id)

    def remember_outcome(self, *, run_id: str, status: str, summary: dict[str, Any],
                         verified: bool, confidence: float = 0.9, project_id: str | None = None) -> int:
        return self._remember(category="outcome", key=f"outcome:{run_id}", value=self._json(summary),
                              confidence=confidence, importance=4 if verified else 2, verified=verified,
                              source_ref=f"company-run:{run_id}", metadata={"run_id": run_id, "status": status}, project_id=project_id)

    def recall(self, query: str, *, top_k: int = 8, categories: set[str] | None = None,
               verified_only: bool = True, project_id: str | None = None) -> list[CompanyMemoryHit]:
        rows = self.memory.retrieve(str(query or ""), top_k=max(1, int(top_k)) * 3,
                                    kinds={COMPANY_MEMORY}, scope=COMPANY, owner_id=self.company_id)
        hits: list[CompanyMemoryHit] = []
        allowed = set(categories or ())
        for row in rows:
            md = row.get("metadata") or {}
            category = str(md.get("category") or "")
            if allowed and category not in allowed:
                continue
            if verified_only and not bool(md.get("verified")):
                continue
            if project_id is not None and str(md.get("project_id") or "") != str(project_id):
                continue
            hits.append(CompanyMemoryHit(
                memory_id=int(row.get("id") or 0), category=category, key=str(row.get("key") or ""),
                value=str(row.get("value") or ""), confidence=float(row.get("confidence") or 0.0),
                importance=int(row.get("importance") or 0), source_ref=row.get("source_ref"),
                metadata=dict(md), score=float(row.get("score") or 0.0),
            ))
            if len(hits) >= max(1, int(top_k)):
                break
        return hits

    def recall_for_goal(self, objective: str, *, top_k: int = 6, project_id: str | None = None) -> list[CompanyMemoryHit]:
        return self.recall(str(objective or ""), top_k=top_k, project_id=project_id)

    def stats(self) -> dict[str, Any]:
        rows = self.memory.list_memories(scope=COMPANY, owner_id=self.company_id, kind=COMPANY_MEMORY, limit=100000)
        counts: dict[str, int] = {}
        verified = 0
        for row in rows:
            md = row.get("metadata") or {}
            category = str(md.get("category") or "unknown")
            counts[category] = counts.get(category, 0) + 1
            verified += 1 if md.get("verified") else 0
        return {"company_id": self.company_id, "scope": COMPANY, "memory_type": COMPANY_MEMORY,
                "total": len(rows), "verified": verified, "categories": dict(sorted(counts.items()))}

    def forget(self, *, category: str, key: str, reason: str = "company_forget") -> bool:
        canonical = key if key.startswith(f"{category}:") else f"{category}:{key}"
        return self.memory.forget(canonical, kind=COMPANY_MEMORY, scope=COMPANY, owner_id=self.company_id, reason=reason) > 0


def get_company_memory(memory=None, *, company_id: str = DEFAULT_COMPANY_MEMORY_OWNER) -> CompanyMemory:
    """Lazily create the company-memory facade; importing the module has no storage side effects."""
    return CompanyMemory(memory, company_id=company_id)

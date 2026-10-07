from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable

from .capability_planning import CapabilityCandidate, CapabilityRequirement, ExecutiveCapabilitySynthesizer


@dataclass(frozen=True)
class RoutingEvidence:
    role_key: str
    department: str
    capability: str
    tool: str
    attempts: int
    verified_successes: int
    verified_failures: int
    success_rate: float
    workload: float
    active_tasks: int

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["success_rate"] = round(self.success_rate, 4)
        data["workload"] = round(self.workload, 4)
        return data


@dataclass(frozen=True)
class RoutingCandidate:
    candidate: CapabilityCandidate
    evidence_score: float
    workload_score: float
    risk_score: float
    cost_score: float
    routing_score: float
    evidence: RoutingEvidence | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "evidence_score": round(self.evidence_score, 4),
            "workload_score": round(self.workload_score, 4),
            "risk_score": round(self.risk_score, 4),
            "cost_score": round(self.cost_score, 4),
            "routing_score": round(self.routing_score, 4),
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "reason": self.reason,
        }


class AdaptiveDelegationController:
    """Load-aware routing over already-qualified organizational candidates.

    Ownership and qualification are resolved upstream. This controller only ranks candidates
    using verified evidence, current canonical portfolio load, risk, cost, and capability fit.
    It cannot create authority, rewrite ownership, or make an unqualified candidate eligible.
    """

    def __init__(self, organization: Any, learning_store: Any):
        if organization is None or not hasattr(organization, "resolve_owner") or not hasattr(organization, "role"):
            raise TypeError("organization registry is required")
        if learning_store is None or not hasattr(learning_store, "company_delegation_evidence"):
            raise TypeError("canonical LearningStore is required")
        if not hasattr(learning_store, "list_company_projects") or not hasattr(learning_store, "list_company_project_tasks"):
            raise TypeError("canonical LearningStore with portfolio state is required")
        self.organization = organization
        self.learning = learning_store

    def _workload(self, role_key: str) -> tuple[int, float]:
        active = 0
        for project in self.learning.list_company_projects(active_only=True):
            for task in self.learning.list_company_project_tasks(str(project.get("project_id") or ""), active_only=True):
                if str(task.get("specialist") or "") == role_key:
                    active += 1
        return active, min(1.0, active / 5.0)

    def _evidence(self, candidate: CapabilityCandidate) -> RoutingEvidence | None:
        try:
            rows = self.learning.company_delegation_evidence(capability=candidate.capability, limit=500)
        except Exception:
            return None
        matches = [
            row for row in rows
            if str(row.get("specialist") or "") == candidate.specialist
            and str(row.get("tool") or "") == candidate.tool
        ]
        if not matches:
            return None
        row = matches[0]
        attempts = max(0, int(row.get("attempts") or 0))
        successes = max(0, min(attempts, int(row.get("verified_successes") or 0)))
        failures = max(0, int(row.get("verified_failures") or 0))
        active, workload = self._workload(candidate.specialist)
        return RoutingEvidence(
            role_key=candidate.specialist,
            department=str(row.get("department") or candidate.department),
            capability=candidate.capability,
            tool=candidate.tool,
            attempts=attempts,
            verified_successes=successes,
            verified_failures=failures,
            success_rate=successes / max(1, attempts),
            workload=workload,
            active_tasks=active,
        )

    @staticmethod
    def _risk_score(risk: str) -> float:
        return {"low": 1.0, "medium": 0.7, "high": 0.4}.get(str(risk or "").casefold(), 0.5)

    @staticmethod
    def _cost_score(cost: float) -> float:
        return 1.0 / (1.0 + max(0.0, float(cost or 0.0)))

    def rank(self, candidates: Iterable[CapabilityCandidate]) -> tuple[RoutingCandidate, ...]:
        ranked: list[RoutingCandidate] = []
        for candidate in tuple(candidates or ()):
            # Re-check the structured owner so this controller cannot become an ownership bypass.
            try:
                owner = self.organization.resolve_owner(skill_key=candidate.skill_key,
                                                        capability=candidate.capability,
                                                        tool=None)
            except Exception:
                continue
            if owner.department != candidate.department:
                continue
            try:
                role = self.organization.role(candidate.specialist)
            except Exception:
                continue
            if role.department != candidate.department or role.agent_class != "builder":
                continue
            evidence = self._evidence(candidate)
            evidence_score = evidence.success_rate if evidence is not None and evidence.attempts else 0.0
            workload_score = 0.0 if evidence is None else evidence.workload
            risk_score = self._risk_score(candidate.risk)
            cost_score = self._cost_score(candidate.cost)
            # Fit remains dominant. Evidence and capacity are secondary routing signals.
            score = (
                0.60 * max(0.0, min(1.0, float(candidate.fit)))
                + 0.20 * evidence_score
                + 0.15 * (1.0 - workload_score)
                + 0.03 * risk_score
                + 0.02 * cost_score
            )
            reason = "qualified ownership and capability fit preserved; evidence, current load, risk, and cost ranked secondarily"
            ranked.append(RoutingCandidate(candidate, evidence_score, workload_score, risk_score, cost_score, score, evidence, reason))
        ranked.sort(key=lambda item: (
            -item.routing_score,
            -item.candidate.fit,
            -item.evidence_score,
            item.workload_score,
            item.candidate.cost,
            item.candidate.specialist,
            item.candidate.tool,
        ))
        return tuple(ranked)

    def rank_requirement(self, requirement: CapabilityRequirement, *, tool_registry: dict[str, Any]) -> tuple[RoutingCandidate, ...]:
        synthesizer = ExecutiveCapabilitySynthesizer()
        candidates = synthesizer.candidates_for(requirement, registry=tool_registry, organization=self.organization)
        return self.rank(candidates)

    def choose(self, requirement: CapabilityRequirement, *, tool_registry: dict[str, Any]) -> RoutingCandidate | None:
        ranked = self.rank_requirement(requirement, tool_registry=tool_registry)
        return ranked[0] if ranked else None

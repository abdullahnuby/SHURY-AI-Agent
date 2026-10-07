from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, TYPE_CHECKING

from .capability_planning import CapabilityCandidate, CapabilityRequirement, ExecutiveCapabilityPlan, ExecutiveCapabilitySynthesizer
from .models import AgentRole

if TYPE_CHECKING:
    from .registry import OrganizationRegistry


@dataclass(frozen=True)
class CompanyTeamMember:
    role_key: str
    department: str
    covered_requirements: tuple[str, ...]
    covered_capabilities: tuple[str, ...]
    skills: tuple[str, ...]
    selection_score: float
    history_score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_key": self.role_key,
            "department": self.department,
            "covered_requirements": list(self.covered_requirements),
            "covered_capabilities": list(self.covered_capabilities),
            "skills": list(self.skills),
            "selection_score": round(self.selection_score, 4),
            "history_score": round(self.history_score, 4),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExecutiveTeamPlan:
    objective: str
    requirement_keys: tuple[str, ...]
    members: tuple[CompanyTeamMember, ...]
    selected_candidates: tuple[CapabilityCandidate, ...]
    uncovered: tuple[str, ...] = ()
    selection_mode: str = "minimum-specialist-set"
    rationale: str = ""

    @property
    def valid(self) -> bool:
        return bool(self.requirement_keys) and not self.uncovered and bool(self.members)

    @property
    def departments(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(member.department for member in self.members))

    @property
    def specialist_count(self) -> int:
        return len(self.members)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "objective": self.objective,
            "requirement_keys": list(self.requirement_keys),
            "specialist_count": self.specialist_count,
            "department_count": len(self.departments),
            "departments": list(self.departments),
            "members": [member.to_dict() for member in self.members],
            "selected_candidates": [candidate.to_dict() for candidate in self.selected_candidates],
            "uncovered": list(self.uncovered),
            "selection_mode": self.selection_mode,
            "rationale": self.rationale,
        }


class ExecutiveTeamFormer:
    """Choose the smallest effective team from the existing capability candidates.

    The former never looks at raw goal wording. It consumes structured capability requirements
    and the same tool/SkillBank candidates already produced by C5/C7. Verified runtime history
    is used only as a tie-breaker after coverage and team size, so history cannot override
    ownership or make an unqualified specialist eligible.
    """

    _TOP_CANDIDATES = 8
    _MAX_STATES = 2048

    @staticmethod
    def _history_score(candidate: CapabilityCandidate, skill_bank: Any, competency: Any = None) -> float:
        if not candidate.skill_key:
            return 0.0
        try:
            skill = skill_bank.get(candidate.skill_key)
        except Exception:
            return 0.0
        total = int(getattr(skill, "success_count", 0) or 0) + int(getattr(skill, "failure_count", 0) or 0)
        if total:
            empirical = int(getattr(skill, "success_count", 0) or 0) / total
            base = max(0.0, min(1.0, 0.72 * empirical + 0.28 * float(getattr(skill, "confidence", 0.0) or 0.0)))
        else:
            base = max(0.0, min(1.0, float(getattr(skill, "confidence", 0.0) or 0.0) * 0.5))
        if competency is None:
            return base
        try:
            evidence_score = float(competency.score(capability=candidate.capability, specialist=candidate.specialist, tool=candidate.tool))
        except Exception:
            evidence_score = 0.0
        if evidence_score <= 0.0:
            return base
        return max(0.0, min(1.0, 0.60 * base + 0.40 * evidence_score))

    @staticmethod
    def _candidate_value(candidate: CapabilityCandidate, history_score: float, existing_specialists: set[str]) -> float:
        shared_bonus = 0.35 if candidate.specialist in existing_specialists else 0.0
        risk_penalty = {"low": 0.0, "medium": 0.08, "high": 0.18}.get(candidate.risk.casefold(), 0.12)
        return float(candidate.fit) + 0.25 * history_score + shared_bonus - 0.05 * risk_penalty - 0.01 * max(0.0, candidate.cost)

    def form(
        self,
        *,
        objective: str,
        capability_plan: ExecutiveCapabilityPlan,
        organization: "OrganizationRegistry",
        tool_registry: dict[str, Any],
        learning_store: Any = None,
    ) -> ExecutiveTeamPlan:
        if not capability_plan.requirements:
            return ExecutiveTeamPlan(str(objective or ""), (), (), (), (), rationale="no structured capability requirements")

        from app.skills.registry import SkillBank
        from app.learning.store import LearningStore
        from .competency import CompanyCompetencyCalibrator
        from .routing import AdaptiveDelegationController
        skill_bank = SkillBank()
        learning = learning_store or LearningStore()
        try:
            competency = CompanyCompetencyCalibrator(learning)
        except Exception:
            competency = None
        try:
            routing = AdaptiveDelegationController(organization, learning)
        except Exception:
            routing = None
        pools: dict[str, tuple[CapabilityCandidate, ...]] = {}
        uncovered: list[str] = []
        synthesizer = ExecutiveCapabilitySynthesizer()
        for requirement in capability_plan.requirements:
            try:
                candidates = synthesizer.candidates_for(requirement, registry=tool_registry, organization=organization)
            except Exception:
                candidates = ()
            if not candidates:
                uncovered.append(f"{requirement.key}:{requirement.capability}")
                continue
            pools[requirement.key] = tuple(candidates[: self._TOP_CANDIDATES])

        if uncovered:
            return ExecutiveTeamPlan(
                str(objective or ""),
                tuple(req.key for req in capability_plan.requirements),
                (),
                (),
                tuple(uncovered),
                rationale="team formation is blocked because one or more required capabilities have no qualified organizational candidate",
            )

        requirements = tuple(capability_plan.requirements)
        # Resolve the hardest requirements first to preserve scarce specialists.
        requirements = tuple(sorted(requirements, key=lambda req: (len(pools[req.key]), req.key)))

        # State value: specialist-set, selected-candidates, total-fit, total-history, cost.
        states: dict[frozenset[str], tuple[tuple[CapabilityCandidate, ...], float, float, float]] = {frozenset(): ((), 0.0, 0.0, 0.0)}
        for requirement in requirements:
            next_states: dict[frozenset[str], tuple[tuple[CapabilityCandidate, ...], float, float, float]] = {}
            for specialist_set, (chosen, fit_sum, hist_sum, cost_sum) in states.items():
                existing = set(specialist_set)
                for candidate in pools[requirement.key]:
                    new_set = frozenset((*specialist_set, candidate.specialist))
                    history = self._history_score(candidate, skill_bank, competency)
                    candidate_value = self._candidate_value(candidate, history, existing)
                    if routing is not None:
                        ranked = routing.rank((candidate,))
                        if ranked:
                            candidate_value += 0.02 * ranked[0].routing_score
                    row = (chosen + (candidate,), fit_sum + candidate_value, hist_sum + history, cost_sum + max(0.0, candidate.cost))
                    previous = next_states.get(new_set)
                    if previous is None or (row[1], row[2], -row[3]) > (previous[1], previous[2], -previous[3]):
                        next_states[new_set] = row
            # Keep deterministic bounded state space while preferring fewer specialists.
            ranked = sorted(
                next_states.items(),
                key=lambda item: (len(item[0]), -item[1][1], -item[1][2], item[1][3], tuple(c.tool for c in item[1][0])),
            )[: self._MAX_STATES]
            states = dict(ranked)

        best_set, (chosen, fit_sum, hist_sum, cost_sum) = min(
            states.items(),
            key=lambda item: (len(item[0]), -item[1][1], -item[1][2], item[1][3], tuple(sorted(item[0]))),
        )
        candidate_by_requirement = {candidate.requirement_key: candidate for candidate in chosen}

        grouped: dict[str, list[CapabilityCandidate]] = {}
        for candidate in chosen:
            grouped.setdefault(candidate.specialist, []).append(candidate)
        members: list[CompanyTeamMember] = []
        for specialist_key in sorted(grouped):
            role: AgentRole = organization.role(specialist_key)
            rows = sorted(grouped[specialist_key], key=lambda c: c.requirement_key)
            member_history = sum(self._history_score(c, skill_bank, competency) for c in rows) / max(1, len(rows))
            capabilities = tuple(dict.fromkeys(c.capability for c in rows))
            skills = tuple(dict.fromkeys(c.skill_key for c in rows if c.skill_key))
            history_observations = 0
            for candidate in rows:
                if candidate.skill_key:
                    try:
                        skill = skill_bank.get(candidate.skill_key)
                        history_observations += int(getattr(skill, "success_count", 0) or 0) + int(getattr(skill, "failure_count", 0) or 0)
                    except Exception:
                        pass
            reason = (
                f"covers {len(rows)} required capability requirement(s); qualified ownership proven; "
                "team-size minimization preferred this specialist"
            )
            if history_observations > 0:
                reason += "; verified SkillBank runtime history used as quality tie-breaker"
            else:
                reason += "; no verified runtime history available, so SkillBank confidence was used conservatively"
            members.append(CompanyTeamMember(
                role_key=role.key,
                department=role.department,
                covered_requirements=tuple(c.requirement_key for c in rows),
                covered_capabilities=capabilities,
                skills=skills,
                selection_score=sum(c.fit for c in rows) / max(1, len(rows)),
                history_score=member_history,
                reason=reason,
            ))

        rationale = (
            f"CEO selected {len(members)} specialist(s) to cover {len(requirements)} required capability requirement(s); "
            "minimum specialist count is primary, then candidate fit/history/cost are used deterministically."
        )
        return ExecutiveTeamPlan(
            str(objective or ""),
            tuple(req.key for req in capability_plan.requirements),
            tuple(members),
            tuple(candidate_by_requirement[req.key] for req in capability_plan.requirements),
            (),
            rationale=rationale,
        )

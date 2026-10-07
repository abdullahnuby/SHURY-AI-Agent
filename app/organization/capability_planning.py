from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, TYPE_CHECKING

from app.brain.models import PlannedAction

from .models import CompanyTask
if TYPE_CHECKING:
    from .registry import OrganizationRegistry


@dataclass(frozen=True)
class CapabilityRequirement:
    """A CEO-level requirement derived from structured task state, never raw wording."""
    key: str
    objective: str
    capability: str
    source: str
    depends_on: tuple[str, ...] = ()
    expected_effects: tuple[str, ...] = ()
    confidence: float = 1.0
    arguments: dict[str, Any] | None = None
    preferred_tool: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "objective": self.objective,
            "capability": self.capability,
            "source": self.source,
            "depends_on": list(self.depends_on),
            "expected_effects": list(self.expected_effects),
            "confidence": round(max(0.0, min(1.0, float(self.confidence))), 3),
            "arguments": dict(self.arguments or {}),
            "preferred_tool": self.preferred_tool,
        }


@dataclass(frozen=True)
class CapabilityCandidate:
    requirement_key: str
    tool: str
    skill_key: str
    capability: str
    department: str
    specialist: str
    fit: float
    cost: float
    risk: str
    verification_level: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_key": self.requirement_key,
            "tool": self.tool,
            "skill_key": self.skill_key,
            "capability": self.capability,
            "department": self.department,
            "specialist": self.specialist,
            "fit": round(float(self.fit), 4),
            "cost": round(float(self.cost), 4),
            "risk": self.risk,
            "verification_level": self.verification_level,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExecutiveCapabilityPlan:
    requirements: tuple[CapabilityRequirement, ...] = ()
    selected: tuple[CapabilityCandidate, ...] = ()
    alternatives: tuple[CapabilityCandidate, ...] = ()
    unresolved: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return bool(self.requirements) and not self.unresolved and len(self.selected) == len(self.requirements)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "requirements": [x.to_dict() for x in self.requirements],
            "selected": [x.to_dict() for x in self.selected],
            "alternatives": [x.to_dict() for x in self.alternatives],
            "unresolved": list(self.unresolved),
        }


class ExecutiveCapabilitySynthesizer:
    """Turn structured goal/task state into organization-owned capabilities.

    The synthesizer is intentionally conservative:
    - it consumes semantic/TaskIR/plan fields, not benchmark strings;
    - it only selects tools whose declared capability is an exact structural match;
    - organization ownership is proven through the registry;
    - it can emit an executable provisional plan only when every requirement is resolved.
    """

    _VERIFICATION_SCORE = {"strong": 0.20, "standard": 0.10, "weak": 0.0}
    _RISK_PENALTY = {"low": 0.0, "medium": 0.08, "high": 0.18}

    def requirements_from(
        self,
        *,
        semantic: Any = None,
        task_ir: Any = None,
        plan: Iterable[Any] = (),
    ) -> tuple[CapabilityRequirement, ...]:
        requirements: list[CapabilityRequirement] = []
        planned_steps = tuple(plan or ())
        if planned_steps:
            for index, step in enumerate(planned_steps, 1):
                capability = str(getattr(step, "capability", "") or "").strip()
                if not capability:
                    continue
                requirements.append(CapabilityRequirement(
                    key=str(getattr(step, "step_id", getattr(step, "id", "")) or f"s{index}"),
                    objective=str(getattr(step, "objective", "") or "").strip(),
                    capability=capability,
                    source="planned-action",
                    depends_on=tuple(str(x) for x in (getattr(step, "depends_on", ()) or ())),
                    expected_effects=tuple(str(x) for x in (getattr(step, "expected_effects", ()) or ()) if str(x)),
                    confidence=1.0,
                    arguments=dict(getattr(step, "args", {}) or {}),
                    preferred_tool=str(getattr(step, "tool", "") or ""),
                ))

        if not requirements and task_ir is not None:
            for node in tuple(getattr(task_ir, "nodes", ()) or ()):
                capability = str(getattr(node, "capability", "") or "").strip()
                objective = str(getattr(node, "objective", "") or getattr(node, "planner_goal", "") or "").strip()
                if not capability:
                    continue
                requirements.append(CapabilityRequirement(
                    key=str(getattr(node, "id", "") or f"requirement:{len(requirements)+1}"),
                    objective=objective,
                    capability=capability,
                    source="task-ir",
                    depends_on=tuple(str(x) for x in (getattr(node, "depends_on", ()) or ())),
                    expected_effects=(),
                    confidence=float(getattr(node, "confidence", 1.0) or 1.0),
                    arguments=dict(getattr(node, "arguments", {}) or {}),
                    preferred_tool="",
                ))

        if not requirements and semantic is not None:
            capability = str(getattr(semantic, "requested_operation", "") or "").strip()
            if capability:
                requirements.append(CapabilityRequirement(
                    key="goal:1",
                    objective=str(getattr(semantic, "text", "") or "").strip(),
                    capability=capability,
                    source="semantic-contract",
                    depends_on=(),
                    expected_effects=(),
                    confidence=1.0,
                    arguments={},
                    preferred_tool="",
                ))
        return tuple(requirements)

    def candidates_for(
        self,
        requirement: CapabilityRequirement,
        *,
        registry: dict[str, Any],
        organization: OrganizationRegistry,
    ) -> tuple[CapabilityCandidate, ...]:
        rows: list[CapabilityCandidate] = []
        target = requirement.capability.casefold().strip()
        skill_options = ()
        try:
            from app.skills.registry import SkillBank
            skill_bank = SkillBank()
            index = organization.skill_index(skill_bank)
            skill_options = index.skills_for_capability(requirement.capability)
        except Exception:
            skill_options = ()
        tool_to_skills = {}
        for skill in skill_options:
            for item in skill_bank.get(skill.key).workflow:
                if isinstance(item, dict):
                    tname = str(item.get("tool", "") or "").strip()
                    if tname:
                        tool_to_skills.setdefault(tname, []).append(skill)
        for name, tool in registry.items():
            capability = str(getattr(tool, "capability", "") or name).strip()
            capability_key = capability.casefold()
            name_key = str(name or '').casefold()
            if capability_key != target and name_key != target:
                continue
            skill_key = ""
            matched_skills = tool_to_skills.get(name, ())
            if matched_skills:
                skill_key = matched_skills[0].key
            try:
                owner = organization.resolve_owner(
                    skill_key=skill_key,
                    capability=capability,
                    expected_effects=requirement.expected_effects,
                    tool=tool,
                )
                specialist = organization.select_specialist(owner.department, capability=capability, tool=tool)
            except (ValueError, KeyError):
                continue
            verification = str(getattr(tool, "verification_level", "standard") or "standard").casefold()
            risk = str(getattr(tool, "risk", "low") or "low").casefold()
            cost = float(getattr(tool, "cost", 1.0) or 1.0)
            fit = 1.0 + self._VERIFICATION_SCORE.get(verification, 0.0) - self._RISK_PENALTY.get(risk, 0.12)
            if requirement.preferred_tool and name == requirement.preferred_tool:
                fit += 0.25
            fit -= min(0.25, max(0.0, cost) * 0.01)
            rows.append(CapabilityCandidate(
                requirement_key=requirement.key,
                tool=name,
                skill_key=skill_key,
                capability=capability,
                department=owner.department,
                specialist=specialist.key,
                fit=fit,
                cost=cost,
                risk=risk,
                verification_level=verification,
                reason=("preferred planned tool + SkillBank competency + organizational ownership" if requirement.preferred_tool and name == requirement.preferred_tool and skill_key else ("SkillBank competency + exact capability ownership" if skill_key else "exact declared capability + organizational ownership")),
            ))
        rows.sort(key=lambda x: (-x.fit, x.cost, x.tool))
        return tuple(rows)

    def synthesize(
        self,
        *,
        semantic: Any = None,
        task_ir: Any = None,
        plan: Iterable[Any] = (),
        registry: dict[str, Any],
        organization: OrganizationRegistry,
    ) -> ExecutiveCapabilityPlan:
        requirements = self.requirements_from(semantic=semantic, task_ir=task_ir, plan=plan)
        selected: list[CapabilityCandidate] = []
        alternatives: list[CapabilityCandidate] = []
        unresolved: list[str] = []
        for requirement in requirements:
            candidates = self.candidates_for(requirement, registry=registry, organization=organization)
            if not candidates:
                unresolved.append(f"{requirement.key}:{requirement.capability}")
                continue
            selected.append(candidates[0])
            alternatives.extend(candidates[1:4])
        return ExecutiveCapabilityPlan(tuple(requirements), tuple(selected), tuple(alternatives), tuple(unresolved))

    def synthesize_executable_plan(
        self,
        *,
        semantic: Any,
        task_ir: Any,
        registry: dict[str, Any],
        organization: OrganizationRegistry,
    ) -> tuple[list[PlannedAction], ExecutiveCapabilityPlan]:
        capability_plan = self.synthesize(
            semantic=semantic,
            task_ir=task_ir,
            plan=(),
            registry=registry,
            organization=organization,
        )
        if not capability_plan.valid:
            return [], capability_plan
        selected_by_key = {x.requirement_key: x for x in capability_plan.selected}
        actions: list[PlannedAction] = []
        for requirement in capability_plan.requirements:
            candidate = selected_by_key[requirement.key]
            tool = registry[candidate.tool]
            args: dict[str, Any] = {}
            try:
                args.update(dict(tool.args_for(requirement.objective) or {}))
            except Exception:
                args = {}
            args.update(dict(requirement.arguments or {}))
            for dep in requirement.depends_on:
                # Dependencies are rewritten below from TaskIR node ids to runtime step ids.
                _ = dep
            try:
                arg_errors = tuple(tool.validate_args(args) or ())
            except Exception:
                arg_errors = ()
            if arg_errors:
                return [], capability_plan
            actions.append(PlannedAction(
                step_id=f"s{len(actions)+1}",
                capability=candidate.capability,
                tool=candidate.tool,
                args=args,
                depends_on=(),
                expected_effects=tuple(getattr(tool, "produces", ()) or ()),
                rationale="CEO capability synthesis: exact capability contract + organizational ownership",
            ))
        index_by_req = {req.key: i for i, req in enumerate(capability_plan.requirements)}
        rewritten: list[PlannedAction] = []
        for idx, (requirement, action) in enumerate(zip(capability_plan.requirements, actions), 1):
            deps = tuple(
                f"s{index_by_req[dep] + 1}"
                for dep in requirement.depends_on
                if dep in index_by_req
            )
            rewritten.append(PlannedAction(
                step_id=action.step_id,
                capability=action.capability,
                tool=action.tool,
                args=action.args,
                depends_on=deps,
                expected_effects=action.expected_effects,
                rationale=action.rationale,
            ))
        return rewritten, capability_plan

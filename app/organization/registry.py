from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import AgentRole, Department, CompanyAssignment, CompanyCoordination, CompanyHandoff, CompanyTask, Ownership
from .decomposition import ExecutiveDecomposer
from .capability_planning import ExecutiveCapabilitySynthesizer
from .context import DepartmentExecutionContext
from .scheduler import CompanyScheduler
from .skills import OrganizationSkillIndex
from .evidence import CompanyEvidencePolicy, SourceRegistry, EvidenceAssessment
from .team import ExecutiveTeamFormer, ExecutiveTeamPlan


class OrganizationRoutingError(ValueError):
    """Raised when the organization cannot prove who owns a capability."""


@dataclass(frozen=True)
class OrganizationRegistry:
    roles: tuple[AgentRole, ...]
    departments: tuple[Department, ...]

    def evidence_policy(self) -> CompanyEvidencePolicy:
        return CompanyEvidencePolicy(SourceRegistry())

    def assess_evidence(self, skill_key: str, evidence, *, claims=()) -> EvidenceAssessment:
        return self.evidence_policy().assess(skill_key, evidence, claims=claims)

    def skill_index(self, skill_bank=None) -> OrganizationSkillIndex:
        from app.skills.registry import SkillBank
        return OrganizationSkillIndex(self._catalog(), skill_bank or SkillBank())

    def _catalog(self):
        from .catalog import OrganizationCatalog
        return OrganizationCatalog(name="SHURY Company", version=7, principle="runtime organization", ceo=self.role("executive:chief-executive"), roles=self.roles, departments=self.departments)

    def skills_for_role(self, role_key: str, skill_bank=None):
        return self.skill_index(skill_bank).skills_for_role(role_key)

    def skills_for_department(self, department_key: str, skill_bank=None):
        return self.skill_index(skill_bank).skills_for_department(department_key)

    def skills_for_capability(self, capability: str, skill_bank=None):
        return self.skill_index(skill_bank).skills_for_capability(capability)

    def validate_skill_bindings(self, skill_bank=None) -> tuple[str, ...]:
        return self.skill_index(skill_bank).validate()

    def role(self, key: str) -> AgentRole:
        for role in self.roles:
            if role.key == key:
                return role
        raise KeyError(key)

    def department(self, key: str) -> Department:
        for department in self.departments:
            if department.key == key:
                return department
        raise KeyError(key)

    def skill_owner(self, skill_key: str) -> Ownership | None:
        key = str(skill_key or '').strip()
        if not key:
            return None
        matches = [role for role in self.roles if key in role.skills]
        departments = sorted({role.department for role in matches})
        if len(departments) > 1:
            raise OrganizationRoutingError(f'skill has multiple department owners: {key} -> {departments}')
        if not departments:
            return None
        return Ownership(departments[0], f'structured skill ownership: {key}')

    def capability_owner(self, capability: str) -> Ownership | None:
        key = str(capability or '').strip()
        if not key:
            return None
        matches = [d.key for d in self.departments if key in d.owned_capabilities]
        if len(matches) > 1:
            raise OrganizationRoutingError(f'capability has multiple department owners: {key} -> {matches}')
        return Ownership(matches[0], f'department owns capability: {key}') if matches else None

    def effect_owner(self, effects: Iterable[str]) -> Ownership | None:
        requested = {str(x).strip() for x in (effects or ()) if str(x).strip()}
        if not requested:
            return None
        owners = []
        for department in self.departments:
            overlap = requested.intersection(department.owned_effects)
            if overlap:
                owners.append((department.key, overlap))
        if len(owners) > 1:
            # Multiple effects may intentionally cross departments. That is not an ownership
            # conflict; use an effect owner only when all requested effects share one department.
            all_departments = {x[0] for x in owners}
            if len(all_departments) != 1:
                return None
        if not owners:
            return None
        dept, overlap = owners[0]
        return Ownership(dept, f'department owns expected effects: {sorted(overlap)}')

    def tool_owner(self, tool: Any) -> Ownership | None:
        department = str(getattr(tool, 'organization_department', '') or '').strip()
        if not department:
            return None
        if department not in {d.key for d in self.departments}:
            raise OrganizationRoutingError(f'tool declares unknown organization department: {department}')
        role = str(getattr(tool, 'organization_role', '') or '').strip()
        reason = f'tool declares organization ownership: {getattr(tool, "name", "")}'
        if role:
            owner = self.role(role)
            if owner.department != department:
                raise OrganizationRoutingError(f'tool role/department mismatch: {role} -> {department}')
        return Ownership(department, reason)

    def resolve_owner(self, *, skill_key: str = '', capability: str = '', expected_effects: Iterable[str] = (), tool: Any = None) -> Ownership:
        # Precedence intentionally follows stable facts before tool-specific metadata:
        # skill -> atomic capability -> single-owner effects -> explicit tool declaration.
        owner = self.skill_owner(skill_key)
        if owner:
            return owner
        owner = self.capability_owner(capability)
        if owner:
            return owner
        owner = self.effect_owner(expected_effects)
        if owner:
            return owner
        if tool is not None:
            owner = self.tool_owner(tool)
            if owner:
                return owner
            cap = str(getattr(tool, 'capability', '') or '')
            owner = self.capability_owner(cap)
            if owner:
                return owner
        raise OrganizationRoutingError(
            f'no organization owner proven for skill={skill_key!r}, capability={capability!r}, effects={list(expected_effects or ())!r}'
        )

    def select_specialist(self, department_key: str, *, skill_key: str = '', capability: str = '', tool: Any = None) -> AgentRole:
        department = self.department(department_key)
        candidates = [self.role(key) for key in department.specialists]
        if not candidates:
            return self.role(department.head_agent)
        preferred_role = str(getattr(tool, 'organization_role', '') or '').strip() if tool else ''
        if preferred_role:
            preferred = [r for r in candidates if r.key == preferred_role]
            if preferred:
                return preferred[0]
        exact = [r for r in candidates if skill_key and skill_key in r.skills]
        if exact:
            return exact[0]
        exact = [r for r in candidates if capability and capability in r.capabilities]
        if exact:
            return exact[0]
        return candidates[0]

    def build_execution_context(
        self,
        *,
        assignment: CompanyAssignment | dict[str, Any],
        objective: str,
        coordination: dict[str, Any] | None = None,
        arg_keys: Iterable[str] = (),
        evidence_refs: Iterable[str] = (),
        artifact_refs: Iterable[str] = (),
        tool_registry: dict[str, Any] | None = None,
    ) -> DepartmentExecutionContext:
        data = assignment.to_dict() if hasattr(assignment, 'to_dict') else dict(assignment)
        department = self.department(str(data.get('department') or ''))
        # Least-privilege task scope: the context may invoke only the tool assigned to the
        # current CompanyTask. Department-wide tool discovery remains a registry concern, not
        # an execution-context permission.
        allowed_tools = (str(data.get('tool')), ) if data.get('tool') else ()
        specialist = self.role(str(data.get('specialist') or department.head_agent))
        return DepartmentExecutionContext.from_assignment(
            assignment=data, objective=objective, coordination=coordination, arg_keys=arg_keys,
            evidence_refs=evidence_refs, artifact_refs=artifact_refs,
            owned_capabilities=department.owned_capabilities, allowed_tools=allowed_tools,
        )

    def build_assignment(self, *, objective: str, step: Any, index: int, tool_registry: dict[str, Any] | None = None, project_id: str = "", horizon: str = "medium") -> CompanyAssignment:
        tool_name = str(getattr(step, 'tool', '') or '')
        tool = (tool_registry or {}).get(tool_name)
        skill_key = str(getattr(step, 'skill_key', '') or '')
        capability = str(getattr(step, 'capability', '') or '')
        if not skill_key and capability:
            try:
                from app.skills.registry import SkillBank
                index = self.skill_index(SkillBank())
                matches = index.skills_for_capability(capability)
                if matches:
                    # Prefer a skill whose declared workflow contains this exact tool.
                    selected = next((item for item in matches if any(
                        isinstance(w, dict) and str(w.get('tool', '') or '') == tool_name
                        for w in SkillBank().get(item.key).workflow
                    )), matches[0])
                    skill_key = selected.key
            except Exception:
                pass
        expected_effects = tuple(str(x) for x in (getattr(step, 'expected_effects', ()) or ()) if str(x))
        if not expected_effects and tool is not None:
            expected_effects = tuple(str(x) for x in (getattr(tool, 'produces', ()) or ()) if str(x))
        owner = self.resolve_owner(skill_key=skill_key, capability=capability, expected_effects=expected_effects, tool=tool)
        department = self.department(owner.department)
        specialist = self.select_specialist(owner.department, skill_key=skill_key, capability=capability, tool=tool)
        risk = str(getattr(tool, 'risk', 'low') or 'low').casefold() if tool is not None else 'low'
        reviewers = [department.reviewer] if department.reviewer else []
        if risk in {'medium', 'high'}:
            reviewers.insert(0, 'security:reviewer')
        reviewers = tuple(dict.fromkeys(x for x in reviewers if x))
        return CompanyAssignment(
            objective=str(objective or ''), operation=capability, skill_key=skill_key,
            chief_executive=self.role('executive:chief-executive').key,
            department=department.key, department_head=department.head_agent,
            specialist=specialist.key, reviewers=reviewers,
            authority=self.role(department.head_agent).authority,
            reason=f'CEO routed plan step {index} from structured ownership evidence',
            step_id=str(getattr(step, 'step_id', getattr(step, 'id', '')) or ''),
            tool=tool_name, capability=capability, depends_on=tuple(getattr(step, 'depends_on', ()) or ()),
            expected_effects=expected_effects,
            project_id=str(project_id or getattr(step, 'project_id', '') or ''),
            horizon=str(horizon or getattr(step, 'horizon', '') or 'medium'),
        )

    def coordinate(self, objective: str, assignments: Iterable[CompanyAssignment], *, tool_registry: dict[str, Any] | None = None) -> CompanyCoordination:
        assignments = tuple(assignments or ())
        tasks = tuple(
            CompanyTask(
                task_id=f"company:{a.step_id or i}", objective=str(objective or ''),
                department=a.department, department_head=a.department_head, specialist=a.specialist, step_id=a.step_id,
                tool=a.tool, skill_key=a.skill_key, capability=a.capability,
                depends_on=tuple(dep if str(dep).startswith("company:") else f"company:{dep}" for dep in a.depends_on), expected_effects=a.expected_effects,
                authority=a.authority, reviewers=a.reviewers, project_id=a.project_id, horizon=a.horizon,
            )
            for i, a in enumerate(assignments, 1)
        )
        by_step = {x.step_id: x for x in tasks if x.step_id}
        by_task = {x.task_id: x for x in tasks}
        handoffs: list[CompanyHandoff] = []
        for task in tasks:
            for dependency in task.depends_on:
                producer = by_task.get(dependency) or by_step.get(dependency)
                if not producer or producer.department == task.department:
                    continue
                handoffs.append(CompanyHandoff(
                    handoff_id=f"handoff:{dependency}->{task.step_id}",
                    from_task=producer.task_id, to_task=task.task_id,
                    contract=('dependency-complete', 'producer-observation-available'),
                    producer_department=producer.department, consumer_department=task.department,
                ))
        decomposition = ExecutiveDecomposer().decompose(tasks, handoffs)
        effective_registry = tool_registry or {}
        if not effective_registry:
            try:
                from app.runtime.registry import load_tools
                effective_registry = load_tools()
            except Exception:
                effective_registry = {}
        capability_plan = self.synthesize_capabilities(plan=assignments, tool_registry=effective_registry)
        team_plan = ExecutiveTeamFormer().form(
            objective=objective, capability_plan=capability_plan, organization=self, tool_registry=effective_registry
        )
        schedule = CompanyScheduler().schedule(decomposition.tasks, decomposition.execution_waves, effective_registry)
        schedule_rows = tuple(batch.to_dict() for batch in schedule.batches)
        return CompanyCoordination(
            'SHURY Company', 7, tasks=decomposition.tasks, handoffs=decomposition.handoffs,
            workstreams=decomposition.workstreams, execution_waves=decomposition.execution_waves,
            review_gates=decomposition.review_gates, critical_path=decomposition.critical_path,
            validation_errors=decomposition.errors,
            required_capabilities=tuple(x.to_dict() for x in capability_plan.requirements),
            capability_candidates=tuple(x.to_dict() for x in capability_plan.selected),
            unresolved_capabilities=capability_plan.unresolved,
            execution_context_ids=tuple(f'company-context:company:{task.step_id}' for task in decomposition.tasks),
            execution_schedule=schedule_rows,
            schedule_serial_duration=schedule.serial_duration,
            schedule_estimated_duration=schedule.scheduled_duration,
            schedule_max_parallelism=schedule.max_parallelism,
            schedule_errors=schedule.errors,
            team_formation=team_plan.to_dict(),
        )

    def synthesize_capabilities(self, *, semantic: Any = None, task_ir: Any = None, plan: Iterable[Any] = (), tool_registry: dict[str, Any] | None = None, registry: dict[str, Any] | None = None):
        tools = tool_registry or registry or {}
        return ExecutiveCapabilitySynthesizer().synthesize(
            semantic=semantic, task_ir=task_ir, plan=plan, registry=tools, organization=self
        )

    def form_team(self, *, objective: str, semantic: Any = None, task_ir: Any = None, plan: Iterable[Any] = (), tool_registry: dict[str, Any] | None = None, learning_store: Any = None) -> ExecutiveTeamPlan:
        tools = tool_registry or {}
        if not tools:
            try:
                from app.runtime.registry import load_tools
                tools = load_tools()
            except Exception:
                tools = {}
        capability_plan = self.synthesize_capabilities(semantic=semantic, task_ir=task_ir, plan=plan, tool_registry=tools)
        return ExecutiveTeamFormer().form(
            objective=objective, capability_plan=capability_plan, organization=self, tool_registry=tools, learning_store=learning_store
        )

    def synthesize_executable_plan(self, *, semantic: Any, task_ir: Any, tool_registry: dict[str, Any] | None = None):
        tools = tool_registry or {}
        return ExecutiveCapabilitySynthesizer().synthesize_executable_plan(
            semantic=semantic, task_ir=task_ir, registry=tools, organization=self
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        role_keys = [r.key for r in self.roles]
        dept_keys = [d.key for d in self.departments]
        if len(role_keys) != len(set(role_keys)):
            errors.append('duplicate_agent_role_keys')
        if len(dept_keys) != len(set(dept_keys)):
            errors.append('duplicate_department_keys')
        if 'executive:chief-executive' not in role_keys:
            errors.append('missing_ceo')
        for role in self.roles:
            if role.agent_class == 'reviewer' and role.write_surfaces:
                errors.append(f'reviewer_has_write_surface:{role.key}')
        skill_owners: dict[str, str] = {}
        for role in self.roles:
            for skill in role.skills:
                old = skill_owners.setdefault(skill, role.department)
                if old != role.department:
                    errors.append(f'skill_multiple_departments:{skill}:{old}:{role.department}')
        capability_owners: dict[str, str] = {}
        effect_owners: dict[str, str] = {}
        for dept in self.departments:
            if dept.key not in {r.department for r in self.roles}:
                errors.append(f'department_without_roles:{dept.key}')
            try:
                head = self.role(dept.head_agent)
                if head.department != dept.key:
                    errors.append(f'head_department_mismatch:{dept.key}')
            except KeyError:
                errors.append(f'missing_department_head:{dept.key}')
            for specialist in dept.specialists:
                try:
                    role = self.role(specialist)
                    if role.department != dept.key:
                        errors.append(f'specialist_department_mismatch:{specialist}')
                except KeyError:
                    errors.append(f'missing_specialist:{specialist}')
            for capability in dept.owned_capabilities:
                old = capability_owners.setdefault(capability, dept.key)
                if old != dept.key:
                    errors.append(f'capability_multiple_departments:{capability}:{old}:{dept.key}')
            for effect in dept.owned_effects:
                old = effect_owners.setdefault(effect, dept.key)
                if old != dept.key:
                    errors.append(f'effect_multiple_departments:{effect}:{old}:{dept.key}')
        return list(dict.fromkeys(errors))

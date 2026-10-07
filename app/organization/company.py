from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import AgentRole, CompanyAssignment, Department, OrganizationValidation, ExecutionMandate, CompanyCoordination
from .registry import OrganizationRegistry, OrganizationRoutingError
from .catalog import OrganizationCatalog
from .multi_horizon import CompanyPortfolioManager


CATALOG = OrganizationCatalog.load()
CEO = CATALOG.ceo
ROLES: tuple[AgentRole, ...] = CATALOG.roles
DEPARTMENTS: tuple[Department, ...] = CATALOG.departments


@dataclass(frozen=True)
class SHURYCompany:
    ceo: AgentRole
    roles: tuple[AgentRole, ...]
    departments: tuple[Department, ...]

    @classmethod
    def default(cls) -> 'SHURYCompany':
        return cls(CEO, ROLES, DEPARTMENTS)

    @property
    def registry(self) -> OrganizationRegistry:
        return OrganizationRegistry(self.roles, self.departments)

    @property
    def portfolio(self) -> CompanyPortfolioManager:
        return CompanyPortfolioManager()

    def role(self, key: str) -> AgentRole:
        return self.registry.role(key)

    def department(self, key: str) -> Department:
        return self.registry.department(key)

    def validate(self) -> OrganizationValidation:
        errors: list[str] = []
        if self.ceo.agent_class != 'orchestrator':
            errors.append('ceo_must_be_orchestrator')
        if self.ceo.write_surfaces:
            errors.append('ceo_must_not_own_write_surface')
        errors.extend(self.registry.validate())
        builders = [role for role in self.roles if role.agent_class == 'builder']
        for i, left in enumerate(builders):
            for right in builders[i + 1:]:
                if left.department == right.department:
                    continue
                for a in left.write_surfaces:
                    for b in right.write_surfaces:
                        if a == b:
                            errors.append(f'write_surface_overlap:{left.key}:{right.key}:{a}')
        return OrganizationValidation(valid=not errors, errors=tuple(dict.fromkeys(errors)))

    def discover_skill_owner(self, skill_key: str) -> str | None:
        owner = self.registry.skill_owner(skill_key)
        return owner.department if owner else None

    def route(self, objective: str, operation: str = '', skill_key: str = '', risk: str = 'low', multi_step: bool = True) -> CompanyAssignment:
        from types import SimpleNamespace
        step = SimpleNamespace(
            step_id='direct', tool='', capability=str(operation or ''),
            expected_effects=(), depends_on=(), skill_key=str(skill_key or '')
        )
        # Direct routing may be invoked without a planner-provided registry. Load the
        # same structured tool registry lazily so ownership remains data-driven and
        # never depends on a tool-name-to-department dictionary.
        tool_registry = {}
        if not skill_key or not self.discover_skill_owner(skill_key):
            try:
                from app.runtime.registry import load_tools
                tool_registry = load_tools()
            except Exception:
                tool_registry = {}
        assignment = self.registry.build_assignment(objective=objective, step=step, index=1, tool_registry=tool_registry)
        reviewers = list(assignment.reviewers)
        if risk.casefold() in {'medium', 'high'} and 'security:reviewer' not in reviewers:
            reviewers.insert(0, 'security:reviewer')
        return CompanyAssignment(**{**assignment.__dict__, 'reviewers': tuple(dict.fromkeys(reviewers))})

    def mandate(self, assignment: CompanyAssignment, skill_key: str) -> ExecutionMandate:
        if assignment.chief_executive != self.ceo.key:
            raise PermissionError('execution mandate must originate from the SHURY CEO')
        if not assignment.department or not assignment.specialist:
            raise PermissionError('execution mandate is missing a department or specialist')
        owner = self.discover_skill_owner(skill_key)
        if owner and owner != assignment.department:
            raise PermissionError(f'skill {skill_key} is owned by {owner}, not {assignment.department}')
        specialist = self.role(assignment.specialist)
        if skill_key and specialist.skills and skill_key not in specialist.skills:
            raise PermissionError(f'specialist {specialist.key} does not own skill {skill_key}')
        return ExecutionMandate(
            assignment=assignment, allowed_skill=str(skill_key or ''),
            allowed_department=assignment.department, allowed_specialist=assignment.specialist,
        )

    def snapshot(self) -> dict:
        validation = self.validate()
        from app.skills.registry import SkillBank
        skill_binding_errors = self.registry.validate_skill_bindings(SkillBank())
        portfolio = self.portfolio
        return {
            'name': 'SHURY Company',
            'version': 7,
            'ceo': self.ceo.to_dict(),
            'departments': [x.to_dict() for x in self.departments],
            'agents': [x.to_dict() for x in self.roles],
            'validation': validation.to_dict(),
            'skill_binding_validation': {'valid': not skill_binding_errors, 'errors': list(skill_binding_errors)},
            'routing': {
                'precedence': ['skill', 'capability', 'single-owner-effects', 'tool-declaration', 'tool-capability'],
                'failure_mode': 'fail_closed',
            },
            'portfolio': portfolio.snapshot(),
            'governance': {
                'failure_mode': 'fail_closed',
                'human_approval_source': 'runtime_approval_callback',
                'high_impact_requires_security_reviewer': True,
                'controlled_action_classes': ['destructive', 'external-publication', 'privileged', 'financial'],
                'approval_scope': 'sha256(task_id,tool,args)',
                'reviewers_cannot_execute_producer_actions': True,
            },
        }

    def route_plan(self, objective: str, planned_actions: Iterable[Any], *, tool_registry: dict[str, Any] | None = None, project_id: str = "", horizon: str = "medium", budget: Any = None, learning_store: Any = None) -> tuple[CompanyAssignment, ...]:
        assignments: list[CompanyAssignment] = []
        actions = getattr(planned_actions, 'steps', planned_actions)
        registry = self.registry
        if tool_registry is None:
            try:
                from app.runtime.registry import load_tools
                tool_registry = load_tools()
            except Exception:
                tool_registry = {}
        for index, action in enumerate(tuple(actions or ()), 1):
            assignment = registry.build_assignment(
                objective=objective,
                step=action,
                index=index,
                tool_registry=tool_registry or {},
                project_id=str(project_id or getattr(action, 'project_id', '') or ''),
                horizon=str(horizon or getattr(action, 'horizon', '') or 'medium'),
            )
            if assignment.skill_key:
                self.mandate(assignment, assignment.skill_key)
            assignments.append(assignment)
        if budget is not None:
            from .capacity import CapacityBudgetGuard
            from app.learning.store import LearningStore
            CapacityBudgetGuard(learning_store or LearningStore()).enforce(
                assignments, tool_registry=tool_registry or {}, budget=budget
            )
        return tuple(assignments)

    def coordinate(self, objective: str, plan_or_assignments: Any, *, tool_registry: dict[str, Any] | None = None) -> CompanyCoordination:
        assignments = plan_or_assignments
        actions = getattr(plan_or_assignments, 'steps', None)
        if actions is not None:
            assignments = self.route_plan(objective, plan_or_assignments, tool_registry=tool_registry)
        elif isinstance(plan_or_assignments, (list, tuple)):
            first = plan_or_assignments[0] if plan_or_assignments else None
            if first is not None and not hasattr(first, 'department'):
                assignments = self.route_plan(objective, plan_or_assignments, tool_registry=tool_registry)
        return self.registry.coordinate(objective, assignments, tool_registry=tool_registry)

    def form_team(self, objective: str, *, semantic: Any = None, task_ir: Any = None, plan: Any = (), tool_registry: dict[str, Any] | None = None, learning_store: Any = None):
        return self.registry.form_team(
            objective=objective, semantic=semantic, task_ir=task_ir,
            plan=getattr(plan, 'steps', plan), tool_registry=tool_registry or {}, learning_store=learning_store
        )

    def route_candidates(self, *, capability: str, objective: str = '', tool_registry: dict[str, Any] | None = None, learning_store: Any = None):
        from .capability_planning import CapabilityRequirement
        from .routing import AdaptiveDelegationController
        from app.learning.store import LearningStore
        tools = tool_registry or {}
        if not tools:
            from app.runtime.registry import load_tools
            tools = load_tools()
        requirement = CapabilityRequirement(
            key='company-routing', objective=str(objective or capability), capability=str(capability),
            source='company-routing', confidence=1.0, arguments={}, preferred_tool='',
        )
        controller = AdaptiveDelegationController(self.registry, learning_store or LearningStore())
        return controller.rank_requirement(requirement, tool_registry=tools)

    def synthesize_capabilities(self, objective: str, *, semantic: Any = None, task_ir: Any = None, plan: Any = (), tool_registry: dict[str, Any] | None = None):
        return self.registry.synthesize_capabilities(
            semantic=semantic, task_ir=task_ir, plan=getattr(plan, 'steps', plan), tool_registry=tool_registry or {}
        )

    def synthesize_executable_plan(self, *, semantic: Any, task_ir: Any, tool_registry: dict[str, Any] | None = None):
        return self.registry.synthesize_executable_plan(
            semantic=semantic, task_ir=task_ir, tool_registry=tool_registry or {}
        )

    def decompose(self, objective: str, plan_or_assignments: Any, *, tool_registry: dict[str, Any] | None = None) -> CompanyCoordination:
        """Inspect the CEO-level organization topology without executing the plan."""
        return self.coordinate(objective, plan_or_assignments, tool_registry=tool_registry)


DEFAULT_COMPANY = SHURYCompany.default()

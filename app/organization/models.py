from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

AgentClass = Literal['orchestrator', 'builder', 'reviewer']
Authority = Literal['autonomous', 'proposes', 'escalates']


@dataclass(frozen=True)
class AgentRole:
    key: str
    name: str
    department: str
    parent: str | None
    agent_class: AgentClass
    remit: str
    skills: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    write_surfaces: tuple[str, ...] = ()
    runtime_domains: tuple[str, ...] = ()
    authority: Authority = 'autonomous'

    @property
    def read_only(self) -> bool:
        return self.agent_class == 'reviewer' or not self.write_surfaces

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Department:
    key: str
    name: str
    head_agent: str
    remit: str
    specialists: tuple[str, ...] = ()
    reviewer: str | None = None
    owned_capabilities: tuple[str, ...] = ()
    owned_effects: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CompanyAssignment:
    objective: str
    operation: str
    skill_key: str
    chief_executive: str
    department: str
    department_head: str
    specialist: str
    reviewers: tuple[str, ...] = ()
    authority: Authority = 'autonomous'
    reason: str = ''
    step_id: str = ''
    tool: str = ''
    capability: str = ''
    depends_on: tuple[str, ...] = ()
    expected_effects: tuple[str, ...] = ()
    project_id: str = ''
    horizon: str = 'medium'

    @property
    def chain(self) -> tuple[str, ...]:
        return (self.chief_executive, self.department_head, self.specialist, *self.reviewers)

    def to_dict(self) -> dict:
        data = asdict(self)
        data['chain'] = list(self.chain)
        data['reviewers'] = list(self.reviewers)
        data['depends_on'] = list(self.depends_on)
        data['expected_effects'] = list(self.expected_effects)
        return data


@dataclass(frozen=True)
class OrganizationValidation:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SkillCompetency:
    key: str
    department: str
    roles: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    status: str = ''
    trust_level: str = 'local'
    confidence: float = 0.0
    utility: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['roles'] = list(self.roles)
        data['capabilities'] = list(self.capabilities)
        data['outputs'] = list(self.outputs)
        return data


@dataclass(frozen=True)
class Ownership:
    department: str
    reason: str
    confidence: str = 'structural'

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CompanyTask:
    task_id: str
    objective: str
    department: str
    department_head: str
    specialist: str
    step_id: str
    tool: str
    skill_key: str = ''
    capability: str = ''
    depends_on: tuple[str, ...] = ()
    expected_effects: tuple[str, ...] = ()
    authority: Authority = 'autonomous'
    reviewers: tuple[str, ...] = ()
    project_id: str = ''
    horizon: str = 'medium'

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ('depends_on', 'expected_effects', 'reviewers'):
            data[key] = list(data[key])
        return data


@dataclass(frozen=True)
class CompanyHandoff:
    handoff_id: str
    from_task: str
    to_task: str
    contract: tuple[str, ...]
    producer_department: str
    consumer_department: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['contract'] = list(self.contract)
        return data


@dataclass(frozen=True)
class ExecutiveWorkstream:
    department: str
    department_head: str
    task_ids: tuple[str, ...] = ()
    depends_on_departments: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['task_ids'] = list(self.task_ids)
        data['depends_on_departments'] = list(self.depends_on_departments)
        return data


@dataclass(frozen=True)
class ExecutionWave:
    wave: int
    task_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['task_ids'] = list(self.task_ids)
        return data


@dataclass(frozen=True)
class ReviewGate:
    task_id: str
    reviewers: tuple[str, ...] = ()
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['reviewers'] = list(self.reviewers)
        return data


@dataclass(frozen=True)
class ScheduleWave:
    wave: int
    task_ids: tuple[str, ...] = ()
    mode: str = 'serial'
    estimated_duration: float = 0.0
    reason: str = ''

    def to_dict(self) -> dict[str, Any]:
        return {
            'wave': self.wave,
            'task_ids': list(self.task_ids),
            'mode': self.mode,
            'estimated_duration': self.estimated_duration,
            'reason': self.reason,
        }


@dataclass(frozen=True)
class CompanyCoordination:
    company: str
    version: int
    tasks: tuple[CompanyTask, ...] = ()
    handoffs: tuple[CompanyHandoff, ...] = ()
    workstreams: tuple[ExecutiveWorkstream, ...] = ()
    execution_waves: tuple[ExecutionWave, ...] = ()
    review_gates: tuple[ReviewGate, ...] = ()
    critical_path: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    required_capabilities: tuple[dict[str, Any], ...] = ()
    capability_candidates: tuple[dict[str, Any], ...] = ()
    unresolved_capabilities: tuple[str, ...] = ()
    execution_context_ids: tuple[str, ...] = ()
    execution_schedule: tuple[dict[str, Any], ...] = ()
    schedule_serial_duration: float = 0.0
    schedule_estimated_duration: float = 0.0
    schedule_max_parallelism: int = 1
    schedule_errors: tuple[str, ...] = ()
    team_formation: dict[str, Any] = field(default_factory=dict)
    recovery_decisions: tuple[dict[str, Any], ...] = ()
    active_redelegations: tuple[dict[str, Any], ...] = ()
    evidence_assessments: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            'company': self.company,
            'version': self.version,
            'tasks': [x.to_dict() for x in self.tasks],
            'handoffs': [x.to_dict() for x in self.handoffs],
            'workstreams': [x.to_dict() for x in self.workstreams],
            'execution_waves': [x.to_dict() for x in self.execution_waves],
            'review_gates': [x.to_dict() for x in self.review_gates],
            'critical_path': list(self.critical_path),
            'validation_errors': list(self.validation_errors),
            'required_capabilities': list(self.required_capabilities),
            'capability_candidates': list(self.capability_candidates),
            'unresolved_capabilities': list(self.unresolved_capabilities),
            'execution_context_ids': list(self.execution_context_ids),
            'execution_schedule': list(self.execution_schedule),
            'schedule_serial_duration': self.schedule_serial_duration,
            'schedule_estimated_duration': self.schedule_estimated_duration,
            'schedule_max_parallelism': self.schedule_max_parallelism,
            'schedule_errors': list(self.schedule_errors),
            'team_formation': dict(self.team_formation),
            'recovery_decisions': list(self.recovery_decisions),
            'active_redelegations': list(self.active_redelegations),
            'evidence_assessments': list(self.evidence_assessments),
            'project_ids': sorted(set(str(task.project_id) for task in self.tasks if getattr(task, 'project_id', ''))),
        }


@dataclass(frozen=True)
class GovernanceApproval:
    request_id: str
    action_fingerprint: str
    risk: str
    reason: str
    reviewers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            'request_id': self.request_id,
            'action_fingerprint': self.action_fingerprint,
            'risk': self.risk,
            'reason': self.reason,
            'reviewers': list(self.reviewers),
        }


@dataclass(frozen=True)
class GovernanceDecision:
    allowed: bool
    decision: str
    risk: str
    action_class: str
    reasons: tuple[str, ...] = ()
    reviewers: tuple[str, ...] = ()
    human_approval_required: bool = False
    approval: GovernanceApproval | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'allowed': self.allowed,
            'decision': self.decision,
            'risk': self.risk,
            'action_class': self.action_class,
            'reasons': list(self.reasons),
            'reviewers': list(self.reviewers),
            'human_approval_required': self.human_approval_required,
            'approval': self.approval.to_dict() if self.approval else None,
        }


@dataclass(frozen=True)
class ExecutionMandate:
    """CEO-issued, department-scoped authority for an existing deterministic Skill."""
    assignment: CompanyAssignment
    allowed_skill: str
    allowed_department: str
    allowed_specialist: str

    def authorize(self, skill_key: str, department: str) -> bool:
        return str(skill_key or '') == self.allowed_skill and str(department or '') == self.allowed_department

    def to_dict(self) -> dict:
        return {
            'assignment': self.assignment.to_dict(),
            'allowed_skill': self.allowed_skill,
            'allowed_department': self.allowed_department,
            'allowed_specialist': self.allowed_specialist,
        }

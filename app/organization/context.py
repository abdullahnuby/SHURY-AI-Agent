from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterable
import re


class CompanyContextViolation(ValueError):
    """Raised when a department attempts to consume state outside its task scope."""


_REFERENCE_RE = re.compile(r"\{\{(s\d+)(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[([A-Za-z_][A-Za-z0-9_]*)\])?\}\}")


@dataclass(frozen=True)
class DepartmentExecutionContext:
    """Task-scoped organization context.

    The context contains references and policy, not arbitrary prior departmental state.
    Dependency results are only made available when the current task explicitly depends on
    their step ids. Durable user memory remains governed by the existing memory subsystem;
    Company Phase 3 adds a separate boundary for transient departmental working state.
    """

    context_id: str
    company: str
    task_id: str
    step_id: str
    department: str
    specialist: str
    objective: str
    allowed_tool: str
    allowed_capability: str
    allowed_skill: str
    dependency_steps: tuple[str, ...] = ()
    dependency_task_ids: tuple[str, ...] = ()
    inbound_handoffs: tuple[str, ...] = ()
    outbound_handoffs: tuple[str, ...] = ()
    allowed_input_refs: tuple[str, ...] = ()
    allowed_evidence_refs: tuple[str, ...] = ()
    allowed_artifact_refs: tuple[str, ...] = ()
    owned_capabilities: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    memory_policy: str = 'task_local_only'
    project_id: str = ''
    horizon: str = 'medium'

    def authorize_dependency(self, step_id: str) -> bool:
        return str(step_id or '') in self.dependency_steps

    def authorize_tool(self, tool: str) -> bool:
        return str(tool or '') in self.allowed_tools

    def authorize_capability(self, capability: str) -> bool:
        return not self.allowed_capability or str(capability or '') == self.allowed_capability

    def to_dict(self) -> dict[str, Any]:
        return {
            'context_id': self.context_id,
            'company': self.company,
            'task_id': self.task_id,
            'step_id': self.step_id,
            'department': self.department,
            'specialist': self.specialist,
            'objective': self.objective,
            'allowed_tool': self.allowed_tool,
            'allowed_capability': self.allowed_capability,
            'allowed_skill': self.allowed_skill,
            'dependency_steps': list(self.dependency_steps),
            'dependency_task_ids': list(self.dependency_task_ids),
            'inbound_handoffs': list(self.inbound_handoffs),
            'outbound_handoffs': list(self.outbound_handoffs),
            'allowed_input_refs': list(self.allowed_input_refs),
            'allowed_evidence_refs': list(self.allowed_evidence_refs),
            'allowed_artifact_refs': list(self.allowed_artifact_refs),
            'owned_capabilities': list(self.owned_capabilities),
            'allowed_tools': list(self.allowed_tools),
            'memory_policy': self.memory_policy,
            'project_id': self.project_id,
            'horizon': self.horizon,
        }

    @classmethod
    def from_assignment(
        cls,
        *,
        assignment: dict[str, Any],
        objective: str,
        coordination: dict[str, Any] | None = None,
        arg_keys: Iterable[str] = (),
        evidence_refs: Iterable[str] = (),
        artifact_refs: Iterable[str] = (),
        owned_capabilities: Iterable[str] = (),
        allowed_tools: Iterable[str] = (),
    ) -> 'DepartmentExecutionContext':
        step_id = str(assignment.get('step_id') or '')
        task_id = f'company:{step_id}' if step_id and not step_id.startswith('company:') else step_id
        dependency_steps = tuple(
            str(dep).removeprefix('company:')
            for dep in (assignment.get('depends_on') or ())
            if str(dep).strip()
        )
        dependency_task_ids = tuple(f'company:{dep}' for dep in dependency_steps)
        coordination = dict(coordination or {})
        inbound = []
        outbound = []
        for handoff in coordination.get('handoffs') or ():
            if not isinstance(handoff, dict):
                continue
            if str(handoff.get('to_task') or '') == task_id:
                inbound.append(str(handoff.get('handoff_id') or ''))
            if str(handoff.get('from_task') or '') == task_id:
                outbound.append(str(handoff.get('handoff_id') or ''))

        refs = [f'arg:{str(key)}' for key in arg_keys]
        refs.extend(f'dependency:{step}' for step in dependency_steps)
        refs.append('goal:user-goal')
        derived_evidence = list(str(x) for x in evidence_refs if str(x))
        derived_evidence.extend(f'observation:{step}' for step in dependency_steps)
        derived_artifacts = list(str(x) for x in artifact_refs if str(x))
        derived_artifacts.extend(f'output:{step}' for step in dependency_steps)
        return cls(
            context_id=f'company-context:{str(assignment.get("project_id") or "_global")}:{task_id or "unknown"}',
            company='SHURY Company',
            task_id=task_id,
            step_id=step_id,
            department=str(assignment.get('department') or ''),
            specialist=str(assignment.get('specialist') or ''),
            objective=str(objective or ''),
            allowed_tool=str(assignment.get('tool') or ''),
            allowed_capability=str(assignment.get('capability') or ''),
            allowed_skill=str(assignment.get('skill_key') or ''),
            dependency_steps=dependency_steps,
            dependency_task_ids=dependency_task_ids,
            inbound_handoffs=tuple(x for x in inbound if x),
            outbound_handoffs=tuple(x for x in outbound if x),
            allowed_input_refs=tuple(dict.fromkeys(refs)),
            allowed_evidence_refs=tuple(dict.fromkeys(derived_evidence)),
            allowed_artifact_refs=tuple(dict.fromkeys(derived_artifacts)),
            owned_capabilities=tuple(dict.fromkeys(str(x) for x in owned_capabilities if str(x))),
            allowed_tools=tuple(dict.fromkeys(str(x) for x in allowed_tools if str(x))),
            project_id=str(assignment.get('project_id') or ''),
            horizon=str(assignment.get('horizon') or 'medium'),
        )


def referenced_steps(value: Any) -> tuple[str, ...]:
    found: list[str] = []
    def walk(item: Any) -> None:
        if isinstance(item, str):
            for match in _REFERENCE_RE.finditer(item):
                found.append(match.group(1))
        elif isinstance(item, dict):
            for nested in item.values():
                walk(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                walk(nested)
    walk(value)
    return tuple(dict.fromkeys(found))


_CURRENT_CONTEXT: ContextVar[DepartmentExecutionContext | None] = ContextVar(
    'shury_company_execution_context', default=None
)


def current_company_context() -> DepartmentExecutionContext | None:
    return _CURRENT_CONTEXT.get()


def push_company_context(context: DepartmentExecutionContext):
    return _CURRENT_CONTEXT.set(context)


def pop_company_context(token) -> None:
    _CURRENT_CONTEXT.reset(token)


@contextmanager
def company_context(context: DepartmentExecutionContext):
    token = push_company_context(context)
    try:
        yield context
    finally:
        pop_company_context(token)


def assert_references_allowed(value: Any, context: DepartmentExecutionContext) -> tuple[str, ...]:
    """Reject dependency references that are not explicitly declared by the task."""
    refs = referenced_steps(value)
    forbidden = tuple(step for step in refs if not context.authorize_dependency(step))
    if forbidden:
        raise CompanyContextViolation(
            f'context {context.context_id} cannot access undeclared dependency steps: {list(forbidden)}'
        )
    return refs

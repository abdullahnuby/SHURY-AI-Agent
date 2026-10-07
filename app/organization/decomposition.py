from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import CompanyHandoff, CompanyTask, ExecutionWave, ExecutiveWorkstream, ReviewGate


@dataclass(frozen=True)
class DecompositionResult:
    tasks: tuple[CompanyTask, ...]
    handoffs: tuple[CompanyHandoff, ...]
    workstreams: tuple[ExecutiveWorkstream, ...]
    execution_waves: tuple[ExecutionWave, ...]
    review_gates: tuple[ReviewGate, ...]
    critical_path: tuple[str, ...]
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            'valid': self.valid,
            'tasks': [x.to_dict() for x in self.tasks],
            'handoffs': [x.to_dict() for x in self.handoffs],
            'workstreams': [x.to_dict() for x in self.workstreams],
            'execution_waves': [x.to_dict() for x in self.execution_waves],
            'review_gates': [x.to_dict() for x in self.review_gates],
            'critical_path': list(self.critical_path),
            'errors': list(self.errors),
        }


class ExecutiveDecomposer:
    """Build an inspectable CEO-level DAG from typed CompanyTasks only."""

    def decompose(self, tasks: Iterable[CompanyTask], handoffs: Iterable[CompanyHandoff] = ()) -> DecompositionResult:
        ordered = tuple(tasks or ())
        errors: list[str] = []
        by_id = {task.task_id: task for task in ordered}
        if len(by_id) != len(ordered):
            errors.append('duplicate_company_task_ids')
        for task in ordered:
            if task.task_id in task.depends_on:
                errors.append(f'self_dependency:{task.task_id}')
            for dependency in task.depends_on:
                if dependency not in by_id:
                    errors.append(f'unknown_dependency:{task.task_id}:{dependency}')
        handoff_rows = tuple(handoffs or ())
        if not errors and not self._acyclic(ordered):
            errors.append('dependency_cycle')
        workstreams = self._workstreams(ordered)
        waves = self._waves(ordered) if not errors else ()
        critical_path = self._critical_path(ordered) if not errors else ()
        review_gates = tuple(ReviewGate(task_id=t.task_id, reviewers=t.reviewers, blocking=True) for t in ordered if t.reviewers)
        return DecompositionResult(ordered, handoff_rows, workstreams, waves, review_gates, critical_path, tuple(dict.fromkeys(errors)))

    @staticmethod
    def _workstreams(tasks: tuple[CompanyTask, ...]) -> tuple[ExecutiveWorkstream, ...]:
        by_id = {task.task_id: task for task in tasks}
        grouped: dict[str, list[CompanyTask]] = {}
        for task in tasks:
            grouped.setdefault(task.department, []).append(task)
        rows: list[ExecutiveWorkstream] = []
        for department in sorted(grouped):
            members = grouped[department]
            deps = sorted({
                by_id[d].department for t in members for d in t.depends_on
                if d in by_id and by_id[d].department != department
            })
            rows.append(ExecutiveWorkstream(department, members[0].department_head, tuple(t.task_id for t in members), tuple(deps)))
        return tuple(rows)

    @staticmethod
    def _acyclic(tasks: tuple[CompanyTask, ...]) -> bool:
        by_id = {task.task_id: task for task in tasks}
        visiting: set[str] = set(); visited: set[str] = set()
        def visit(task_id: str) -> bool:
            if task_id in visiting: return False
            if task_id in visited: return True
            visiting.add(task_id)
            for dep in by_id[task_id].depends_on:
                if dep in by_id and not visit(dep): return False
            visiting.remove(task_id); visited.add(task_id); return True
        return all(visit(task.task_id) for task in tasks)

    @staticmethod
    def _waves(tasks: tuple[CompanyTask, ...]) -> tuple[ExecutionWave, ...]:
        by_id = {task.task_id: task for task in tasks}; memo: dict[str, int] = {}
        def depth(task_id: str) -> int:
            if task_id in memo: return memo[task_id]
            value = 1 + max((depth(d) for d in by_id[task_id].depends_on), default=0)
            memo[task_id] = value; return value
        grouped: dict[int, list[str]] = {}
        for task in tasks: grouped.setdefault(depth(task.task_id), []).append(task.task_id)
        return tuple(ExecutionWave(w, tuple(sorted(ids))) for w, ids in sorted(grouped.items()))

    @staticmethod
    def _critical_path(tasks: tuple[CompanyTask, ...]) -> tuple[str, ...]:
        by_id = {task.task_id: task for task in tasks}; memo: dict[str, tuple[str, ...]] = {}
        def path(task_id: str) -> tuple[str, ...]:
            if task_id in memo: return memo[task_id]
            deps = [d for d in by_id[task_id].depends_on if d in by_id]
            if not deps: result = (task_id,)
            else: result = max((path(d) for d in deps), key=lambda p: (len(p), tuple(reversed(p)))) + (task_id,)
            memo[task_id] = result; return result
        return max((path(t.task_id) for t in tasks), key=lambda p: (len(p), tuple(reversed(p))), default=())

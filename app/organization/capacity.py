from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import CompanyAssignment


@dataclass(frozen=True)
class ExecutionBudget:
    """Explicit execution guardrails supplied by the caller.

    A missing limit means that dimension is not constrained. When a limit is supplied,
    the guard fails closed if the canonical evidence required to measure that dimension
    cannot be read.
    """

    max_plan_cost: float | None = None
    max_active_tasks_per_specialist: int | None = None
    max_active_tasks_total: int | None = None

    def __post_init__(self) -> None:
        if self.max_plan_cost is not None and float(self.max_plan_cost) < 0:
            raise ValueError("max_plan_cost must be non-negative")
        for value, field in (
            (self.max_active_tasks_per_specialist, "max_active_tasks_per_specialist"),
            (self.max_active_tasks_total, "max_active_tasks_total"),
        ):
            if value is not None and int(value) < 0:
                raise ValueError(f"{field} must be non-negative")


@dataclass(frozen=True)
class CapacityBudgetDecision:
    allowed: bool
    estimated_plan_cost: float
    active_tasks_total: int
    active_tasks_by_specialist: dict[str, int]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "estimated_plan_cost": round(float(self.estimated_plan_cost), 6),
            "active_tasks_total": int(self.active_tasks_total),
            "active_tasks_by_specialist": dict(self.active_tasks_by_specialist),
            "reasons": list(self.reasons),
        }


class CapacityBudgetGuard:
    """Fail-closed preflight checks over canonical company workload and tool cost."""

    def __init__(self, learning_store: Any):
        required = ("list_company_projects", "list_company_project_tasks")
        if learning_store is None or any(not hasattr(learning_store, name) for name in required):
            raise TypeError("canonical LearningStore with company portfolio state is required")
        self.learning = learning_store

    def _active_workload(self) -> tuple[int, dict[str, int]]:
        total = 0
        by_specialist: dict[str, int] = {}
        try:
            projects = self.learning.list_company_projects(active_only=True)
            for project in projects:
                project_id = str(project.get("project_id") or "")
                tasks = self.learning.list_company_project_tasks(project_id, active_only=True)
                for task in tasks:
                    specialist = str(task.get("specialist") or "").strip()
                    if not specialist:
                        # An active task without an accountable specialist cannot be safely
                        # counted against a specialist budget; total capacity is still measured.
                        specialist = "__unassigned__"
                    total += 1
                    by_specialist[specialist] = by_specialist.get(specialist, 0) + 1
        except Exception as exc:
            raise PermissionError("cannot verify canonical company workload") from exc
        return total, by_specialist

    @staticmethod
    def _tool_cost(tool_name: str, tool_registry: dict[str, Any]) -> float:
        if not tool_name:
            raise PermissionError("cannot verify execution cost for an assignment without a tool")
        if tool_name not in tool_registry:
            raise PermissionError(f"cannot verify execution cost for unknown tool: {tool_name}")
        tool = tool_registry[tool_name]
        try:
            cost = float(getattr(tool, "cost"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise PermissionError(f"cannot verify execution cost for tool: {tool_name}") from exc
        if cost < 0:
            raise PermissionError(f"tool cost must be non-negative: {tool_name}")
        return cost

    def assess(
        self,
        assignments: Iterable[CompanyAssignment],
        *,
        tool_registry: dict[str, Any],
        budget: ExecutionBudget,
    ) -> CapacityBudgetDecision:
        rows = tuple(assignments or ())
        needs_workload = budget.max_active_tasks_per_specialist is not None or budget.max_active_tasks_total is not None
        active_total, active_by_specialist = self._active_workload() if needs_workload else (0, {})

        estimated_plan_cost = 0.0
        reasons: list[str] = []
        projected_by_specialist = dict(active_by_specialist)
        for assignment in rows:
            if budget.max_plan_cost is not None:
                estimated_plan_cost += self._tool_cost(assignment.tool, tool_registry)
            if needs_workload:
                specialist = str(assignment.specialist or "").strip()
                if not specialist:
                    raise PermissionError("cannot verify specialist capacity for an assignment")
                projected_by_specialist[specialist] = projected_by_specialist.get(specialist, 0) + 1

        if budget.max_plan_cost is not None and estimated_plan_cost > float(budget.max_plan_cost) + 1e-9:
            reasons.append("plan_cost_exceeds_budget")
        if budget.max_active_tasks_total is not None and active_total + len(rows) > int(budget.max_active_tasks_total):
            reasons.append("total_active_capacity_exceeded")
        if budget.max_active_tasks_per_specialist is not None:
            limit = int(budget.max_active_tasks_per_specialist)
            for specialist, projected in projected_by_specialist.items():
                if specialist == "__unassigned__":
                    continue
                if projected > limit:
                    reasons.append(f"specialist_capacity_exceeded:{specialist}")

        return CapacityBudgetDecision(
            allowed=not reasons,
            estimated_plan_cost=estimated_plan_cost,
            active_tasks_total=active_total,
            active_tasks_by_specialist=active_by_specialist,
            reasons=tuple(reasons),
        )

    def enforce(
        self,
        assignments: Iterable[CompanyAssignment],
        *,
        tool_registry: dict[str, Any],
        budget: ExecutionBudget,
    ) -> CapacityBudgetDecision:
        decision = self.assess(assignments, tool_registry=tool_registry, budget=budget)
        if not decision.allowed:
            raise PermissionError("company execution budget denied: " + ", ".join(decision.reasons))
        return decision

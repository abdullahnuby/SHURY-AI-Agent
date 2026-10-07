from __future__ import annotations

from types import SimpleNamespace

from app.runtime.registry import load_tools

import pytest

from app.learning.store import LearningStore
from app.organization.capacity import CapacityBudgetGuard, ExecutionBudget
from app.organization.company import DEFAULT_COMPANY


def _tool(cost: float = 2.0):
    return SimpleNamespace(cost=cost)


def _step(step_id: str = "s1", tool: str = "profile_dataset"):
    return SimpleNamespace(
        step_id=step_id,
        tool=tool,
        capability="data_analysis",
        skill_key="",
        expected_effects=(),
        depends_on=(),
    )


def _seed_load(store: LearningStore, specialist: str, count: int):
    store.create_company_project({"project_id": "p1", "name": "P1", "objective": "load"})
    for i in range(count):
        store.upsert_company_project_task({
            "project_id": "p1", "task_id": f"t-{i}", "objective": "active",
            "department": "data", "specialist": specialist, "status": "pending", "ready": True,
        })


def test_c19_budget_allows_within_declared_cost_and_capacity(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    _seed_load(store, "data:data-analyst", 1)
    tools = load_tools()
    assignments = DEFAULT_COMPANY.route_plan(
        "bounded",
        [_step()],
        tool_registry=tools,
    )
    decision = CapacityBudgetGuard(store).assess(
        assignments,
        tool_registry=tools,
        budget=ExecutionBudget(max_plan_cost=2.0, max_active_tasks_per_specialist=2, max_active_tasks_total=3),
    )
    assert decision.allowed is True
    assert decision.estimated_plan_cost == 2.0


def test_c19_cost_budget_denies_before_execution(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tools = load_tools()
    assignments = DEFAULT_COMPANY.route_plan("bounded", [_step()], tool_registry=tools)
    with pytest.raises(PermissionError, match="plan_cost_exceeds_budget"):
        CapacityBudgetGuard(store).enforce(
            assignments,
            tool_registry=tools,
            budget=ExecutionBudget(max_plan_cost=1.0),
        )


def test_c19_specialist_capacity_denies_using_canonical_portfolio(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    _seed_load(store, "data:data-analyst", 2)
    tools = load_tools()
    assignments = DEFAULT_COMPANY.route_plan(
        "bounded",
        [_step()],
        tool_registry=tools,
    )
    # The real registry may choose a different specialist, so target the guard directly with the returned assignment.
    with pytest.raises(PermissionError, match="specialist_capacity_exceeded"):
        CapacityBudgetGuard(store).enforce(
            assignments,
            tool_registry=tools,
            budget=ExecutionBudget(max_active_tasks_per_specialist=2),
        )


def test_c19_fails_closed_when_cost_is_not_verifiable(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tools = load_tools()
    assignments = DEFAULT_COMPANY.route_plan("bounded", [_step()], tool_registry=tools)
    with pytest.raises(PermissionError, match="cannot verify execution cost"):
        CapacityBudgetGuard(store).enforce(
            assignments,
            tool_registry={"profile_dataset": SimpleNamespace()},
            budget=ExecutionBudget(max_plan_cost=1.0),
        )


def test_c19_default_route_behavior_is_unchanged_without_budget():
    assignments = DEFAULT_COMPANY.route_plan("bounded", [_step()], tool_registry=load_tools())
    assert assignments


def test_c19_route_plan_enforces_budget_before_return(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tools = load_tools()
    with pytest.raises(PermissionError, match="plan_cost_exceeds_budget"):
        DEFAULT_COMPANY.route_plan(
            "bounded",
            [_step()],
            tool_registry=tools,
            budget=ExecutionBudget(max_plan_cost=1.0),
            learning_store=store,
        )

"""Failure-aware suffix repair for deterministic plans."""
from __future__ import annotations
from dataclasses import replace

from app.domain.goal import GoalClause, GoalModel
from app.planning.hierarchical import hierarchical_plan
from app.domain.operators import build_operators
from app.domain.plan import Plan, PlanStep, validate
from app.intelligence.understanding import normalize


def _remaining_goal(goal_text: str, completed_clause_indices: set[int]):
    from app.domain.goal import parse_goal
    model = parse_goal(goal_text)
    remaining = [c for c in model.clauses if c.index not in completed_clause_indices]
    remapped = [GoalClause(c.text, c.relation, i) for i, c in enumerate(remaining)]
    return GoalModel(model.original, remapped, dict(model.constraints)), model


def repair_suffix(state, failed_step_id: str, registry: dict, memory=None, max_nodes: int = 20000) -> tuple[Plan | None, dict]:
    """Preserve verified prefix, then re-plan only unfinished clauses from the live state."""
    if not state.plan:
        return None, {"reason": "no_plan"}
    failed = next((s for s in state.plan.steps if s.id == failed_step_id), None)
    if failed is None:
        return None, {"reason": "unknown_step"}
    completed_clause_indices = {s.clause_index for s in state.plan.steps
                                if s.status == "done" and s.clause_index >= 0}
    remaining_goal, original_model = _remaining_goal(state.goal, completed_clause_indices)
    if not remaining_goal.clauses:
        return Plan([s for s in state.plan.steps if s.status == "done"]), {"reason": "nothing_remaining"}

    reliability = {name: memory.tool_reliability_posterior(name) for name in registry} if memory else {}
    fresh_suffix = hierarchical_plan(
        remaining_goal,
        build_operators(registry, reliability),
        registry,
        initial_facts=set(state.world.capabilities),
        initial_resources=dict(state.world.resources),
        max_nodes=max_nodes,
    )
    errors = validate(fresh_suffix, registry)
    if errors or not fresh_suffix.steps:
        return None, {"reason": "no_repair", "errors": errors, "diagnostics": fresh_suffix.diagnostics}

    prefix = [s for s in state.plan.steps if s.status == "done"]
    offset = len(prefix)
    id_map = {}
    repaired_steps: list[PlanStep] = []
    for i, step in enumerate(fresh_suffix.steps, 1):
        new_id = f"s{offset + i}"
        id_map[step.id] = new_id
        repaired = replace(step, id=new_id, status="pending", output=None, error=None, attempts=0,
                           depends_on=[] if not step.depends_on else [id_map[d] for d in step.depends_on])
        repaired_steps.append(repaired)

    # The first repaired step after a sequentially completed prefix is gated by the
    # latest completed step, preserving already verified work.
    if prefix and repaired_steps:
        last_prefix = prefix[-1].id
        first = repaired_steps[0]
        first.depends_on = list(dict.fromkeys(first.depends_on + [last_prefix]))

    combined = Plan(
        steps=prefix + repaired_steps,
        estimated_cost=sum(registry[s.tool].cost for s in prefix + repaired_steps),
        estimated_duration=fresh_suffix.estimated_duration,
        score=fresh_suffix.score,
        planner="v10-suffix-repair",
        diagnostics={
            **fresh_suffix.diagnostics,
            "repaired_from": failed_step_id,
            "preserved_prefix_steps": len(prefix),
            "remaining_clauses": [c.text for c in remaining_goal.clauses],
        },
    )
    return combined, {"reason": "repaired", "old_step": failed_step_id}

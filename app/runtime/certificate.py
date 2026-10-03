"""Deterministic plan certificate.

A certificate is an independently computed proof sketch that a plan can be
simulated from a supplied world state under the registered operator contracts.
It never executes tools and therefore cannot create side effects.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from app.planning.stn import validate_plan_temporal


@dataclass(frozen=True)
class Certificate:
    ok: bool
    errors: tuple[str, ...] = ()
    final_facts: frozenset[str] = frozenset()
    remaining_resources: tuple[tuple[str, float], ...] = ()
    estimated_cost: float = 0.0
    estimated_duration: float = 0.0
    states: tuple[tuple[str, tuple[str, ...]], ...] = field(default_factory=tuple)


def certify_plan(plan, registry, initial_facts=None, initial_resources=None, max_duration=None) -> Certificate:
    if not plan.steps:
        return Certificate(False, ("empty_plan",))
    facts = set(initial_facts or set())
    resources = {k: float(v) for k, v in (initial_resources or {}).items()}
    errors: list[str] = []
    seen: set[str] = set()
    state_log: list[tuple[str, tuple[str, ...]]] = []

    for step in plan.steps:
        tool = registry.get(step.tool)
        if tool is None:
            errors.append(f"{step.id}: unknown_tool")
            continue
        missing_deps = [d for d in step.depends_on if d not in seen]
        if missing_deps:
            errors.append(f"{step.id}: dependency_not_ready:{missing_deps}")
        if step.clause_index >= 0 and step.clause_text and not tool.matches(step.clause_text):
            errors.append(f"{step.id}: tool_does_not_match_clause")
        missing_facts = sorted(set(tool.preconditions) - facts)
        if missing_facts:
            errors.append(f"{step.id}: missing_preconditions:{missing_facts}")
        missing_resources = [r for r in tool.resources_required if r not in resources]
        if missing_resources:
            errors.append(f"{step.id}: missing_resources:{missing_resources}")
        for key, amount in tool.resource_costs:
            if resources.get(key, 0.0) < float(amount) - 1e-9:
                errors.append(f"{step.id}: insufficient_resource:{key}")
        if errors and any(e.startswith(step.id + ":") for e in errors):
            # Continue simulation only when the state transition is still safe.
            continue
        facts.update(tool.produces)
        facts.difference_update(tool.removes)
        for key, amount in tool.resource_costs:
            resources[key] = resources.get(key, 0.0) - float(amount)
        seen.add(step.id)
        state_log.append((step.id, tuple(sorted(facts))))

    temporal_ok, temporal_reason = validate_plan_temporal(plan, registry, max_duration)
    if not temporal_ok:
        errors.append("temporal:" + temporal_reason)
    return Certificate(
        ok=not errors,
        errors=tuple(dict.fromkeys(errors)),
        final_facts=frozenset(facts),
        remaining_resources=tuple(sorted(resources.items())),
        estimated_cost=sum(float(registry[s.tool].cost) for s in plan.steps if s.tool in registry),
        estimated_duration=float(plan.estimated_duration),
        states=tuple(state_log),
    )

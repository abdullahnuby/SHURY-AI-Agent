"""Deterministic partial-order scheduler for V9 plans.

It computes earliest start/finish times from dependencies and serializes
steps that declare the same exclusive resource. It never changes logical
order or tool choice; it only derives a feasible schedule from an already
validated plan.
"""
from dataclasses import dataclass
from app.domain.plan import Plan


@dataclass(frozen=True)
class ScheduledStep:
    step_id: str
    start: float
    finish: float


def schedule(plan: Plan, registry: dict) -> tuple[list[ScheduledStep], float, list[str]]:
    starts: dict[str, float] = {}
    finishes: dict[str, float] = {}
    resource_end: dict[str, float] = {}
    errors: list[str] = []
    out: list[ScheduledStep] = []

    for step in plan.steps:
        if step.tool not in registry:
            errors.append(f"unknown_tool:{step.id}")
            continue
        tool = registry[step.tool]
        start = max((finishes.get(d, 0.0) for d in step.depends_on), default=0.0)
        for res in tool.exclusive_resources:
            start = max(start, resource_end.get(res, 0.0))
        # Zero duration is still an instantaneous event and can share a slot.
        finish = start + max(0.0, float(tool.duration))
        starts[step.id] = start
        finishes[step.id] = finish
        for res in tool.exclusive_resources:
            resource_end[res] = finish
        out.append(ScheduledStep(step.id, start, finish))

    return out, max(finishes.values(), default=0.0), errors


def critical_path(plan: Plan, registry: dict) -> float:
    return schedule(plan, registry)[1]

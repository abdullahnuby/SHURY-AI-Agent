"""Skill-aware adaptive plan selection.

Skills are candidate procedures only. They are grounded against the current TaskIR,
validated and certified against the current world before reuse.
"""
from __future__ import annotations
from dataclasses import replace
from app.domain.plan import Plan, PlanStep, validate
from app.runtime.certificate import certify_plan
from app.skills.registry import SkillCandidate
from app.planning.adaptive_execution import AdaptiveExecutionController
from app.skills.evaluation import summary as skill_eval_summary
from app.planning.capabilities import grounded_args


def skill_to_plan(skill: SkillCandidate, goal: str, registry: dict, task_ir=None) -> Plan | None:
    steps = []
    nodes = list(getattr(task_ir, "nodes", []) or []) if task_ir is not None else []
    for i, item in enumerate(skill.workflow, 1):
        tool_name = item.get("tool")
        tool = registry.get(tool_name)
        if not tool:
            return None
        node = nodes[i - 1] if i - 1 < len(nodes) else None
        source = str(getattr(node, "objective", "") or goal)
        args = tool.args_for(source)
        if node is not None:
            semantic_args = grounded_args(tool, node)
            args = {**args, **semantic_args}
        if tool.pipe_param and (tool.pipe_param not in args or args.get(tool.pipe_param) in (None, "")) and i > 1:
            args = dict(args)
            args[tool.pipe_param] = "{{s%d}}" % (i - 1)
        if tool.validate_args(args):
            return None
        deps = list(item.get("depends_on", []))
        if deps:
            deps = [f"s{d}" if isinstance(d, int) else str(d) for d in deps]
        elif i > 1:
            deps = [f"s{i-1}"]
        steps.append(PlanStep(
            id=f"s{i}", tool=tool_name, args=args,
            clause_index=0,
            clause_text=f"{goal} {tool.name.replace('_', ' ')} {str(tool.capability or '').replace('_', ' ')}",
            capability=tool.capability or tool.name,
            depends_on=deps,
        ))
    if not steps:
        return None
    return Plan(
        steps=steps,
        estimated_cost=sum(registry[s.tool].cost for s in steps),
        estimated_duration=sum(registry[s.tool].duration for s in steps),
        score=sum(registry[s.tool].cost for s in steps),
        planner="v18-skill-candidate",
        diagnostics={"skill_key": skill.key, "skill_version": skill.version,
                     "skill_utility": skill.utility, "skill_status": skill.status},
    )


def choose_adaptive_plan(goal: str, generic: Plan, skills: list[SkillCandidate], registry: dict,
                         initial_facts=None, initial_resources=None, max_duration=None, task_ir=None) -> Plan:
    candidates = [("generic", generic, 0.0)]
    _controller = AdaptiveExecutionController()
    for skill in skills:
        candidate = skill_to_plan(skill, goal, registry, task_ir=task_ir)
        if candidate is None:
            continue
        errors = validate(candidate, registry)
        if errors:
            continue
        cert = certify_plan(candidate, registry, initial_facts or set(), initial_resources or {}, max_duration)
        if not cert.ok:
            continue
        evals = skill_eval_summary(skill.key)
        delta = max(-0.25, min(0.35, float(evals.get("mean_delta", 0.0))))
        utility = 0.62 * skill.utility + 0.18 * delta
        utility -= 0.08 * max(0, len(candidate.steps) - 1)
        utility -= 0.03 * cert.estimated_cost
        utility -= 0.01 * cert.estimated_duration
        current_score = float(generic.score) if generic.steps else float("inf")
        candidate.score = cert.estimated_cost
        candidate.diagnostics["skill_selection_utility"] = utility
        candidate.diagnostics["skill_differential"] = {"count": evals.get("count", 0), "mean_delta": evals.get("mean_delta", 0.0), "recommendation": evals.get("recommendation", "observe")}
        candidate.diagnostics["generic_score"] = current_score
        candidates.append((skill.key, candidate, utility))
    if len(candidates) == 1:
        generic.diagnostics = dict(generic.diagnostics)
        generic.diagnostics["skill_selection"] = {"candidate_skills": [], "selected": None}
        return generic

    generic_cost = sum(registry[s.tool].cost for s in generic.steps) if generic.steps else float("inf")
    skill_choices = [x for x in candidates[1:] if x[1].steps]
    winner = min(skill_choices, key=lambda x: (x[1].estimated_cost, x[1].estimated_duration, -x[2], x[0]))
    diff = winner[1].diagnostics.get("skill_differential", {})
    differential_ok = diff.get("count", 0) < 3 or diff.get("mean_delta", 0.0) >= -0.02
    if winner[1].estimated_cost <= generic_cost * 1.08 and winner[2] >= 0.45 and differential_ok:
        winner[1].planner = "v18-adaptive-skill"
        winner[1].diagnostics["skill_selection"] = {
            "candidate_skills": [x[0] for x in skill_choices], "selected": winner[0],
            "rule": "near-tie current-cost + verified-experience utility",
        }
        return winner[1]
    generic.diagnostics = dict(generic.diagnostics)
    generic.diagnostics["skill_selection"] = {
        "candidate_skills": [x[0] for x in skill_choices], "selected": None,
        "rule": "generic plan retained because current evidence was stronger",
    }
    return generic

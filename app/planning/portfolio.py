"""Deterministic planner portfolio.

Different search procedures fail in different ways. The portfolio keeps the
hierarchical planner as the primary route and uses the bounded V8 best-first
search as an independent fallback/competitor. No external model is required.
"""
from app.planning.hierarchical import hierarchical_plan
from app.planning.search_planner import best_first_plan
from app.runtime.certificate import certify_plan
from app.domain.operators import OperatorRegistry
from app.domain.goal import GoalModel


def portfolio_plan(goal: GoalModel, operators: OperatorRegistry, registry: dict,
                   initial_facts=None, initial_resources=None, max_nodes=20000):
    candidates = []
    h = hierarchical_plan(goal, operators, registry, initial_facts, initial_resources, max_nodes)
    hc = certify_plan(h, registry, initial_facts, initial_resources, goal.constraints.get("max_duration"))
    if hc.ok:
        candidates.append((0, h, hc))

    b = best_first_plan(goal, operators, registry,
                        initial_state=set(initial_facts or set()),
                        initial_resources=dict(initial_resources or {}),
                        max_search_nodes=min(max_nodes, 5000))
    bc = certify_plan(b, registry, initial_facts, initial_resources, goal.constraints.get("max_duration"))
    if bc.ok:
        candidates.append((1, b, bc))

    if not candidates:
        diag = dict(h.diagnostics)
        diag["portfolio"] = {"candidates": 0, "winner": None, "certificate_errors": list(hc.errors) + list(bc.errors)}
        from app.domain.plan import Plan
        return Plan([], 0.0, 0.0, float("inf"), "v10-portfolio", diag)

    def key(item):
        order, plan, cert = item
        # Prefer expected objective encoded by planner score, then cost, duration,
        # then fewer steps, and finally stable algorithm order.
        return (float(plan.score), float(cert.estimated_cost), float(cert.estimated_duration), len(plan.steps), order)

    winner = min(candidates, key=key)
    plan = winner[1]
    plan.planner = "v10-portfolio"
    plan.diagnostics = dict(plan.diagnostics)
    plan.diagnostics["portfolio"] = {
        "candidates": len(candidates),
        "winner": "hierarchical" if winner[0] == 0 else "best_first",
        "certified": True,
        "candidate_planners": ["hierarchical", "best_first"][:len(candidates)],
    }
    return plan

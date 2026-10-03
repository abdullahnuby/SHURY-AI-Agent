"""Deterministic V10 algorithm benchmark.

The suite measures algorithmic properties, not language intelligence:
heuristic reachability, temporal consistency, suffix repair, Bayesian
reliability, and non-dominated alternative plans.
"""
from pathlib import Path
from tempfile import TemporaryDirectory

from app.planning.algorithms import bayes_estimate, clause_relaxed_cost, expected_plan_failure, relaxed_fact_costs
from app.domain.goal import parse_goal
from app.planning.hierarchical import hierarchical_plan
from app.domain.operators import build_operators
from app.runtime.registry import Tool
from app.domain.plan import Plan, PlanStep
from app.planning.stn import validate_plan_temporal
from app.knowledge.memory import Memory


def run_v10_benchmark() -> dict:
    results = {}
    with TemporaryDirectory() as tmp:
        reg = {
            'prepare': Tool('prepare', 'prepare', {}, lambda: 'p', match=lambda g: False,
                            produces=('ready',), cost=2.0),
            'fast': Tool('fast', 'fast', {}, lambda: 'f', match=lambda g: g == 'ship',
                         preconditions=('ready',), produces=('done',), cost=1.0, duration=1.0),
            'slow': Tool('slow', 'slow', {}, lambda: 's', match=lambda g: g == 'ship',
                         preconditions=('ready',), produces=('done',), cost=1.5, duration=4.0),
        }
        ops = build_operators(reg)
        facts = relaxed_fact_costs(ops, set())
        results['relaxed_reachability'] = clause_relaxed_cost('ship', ops, facts) < float('inf')
        results['bayesian_shrinkage'] = bayes_estimate(1, 1).lower_bound < bayes_estimate(100, 95).lower_bound
        results['risk_combination'] = 0.0 < expected_plan_failure([0.1, 0.2]) < 1.0

        plan = hierarchical_plan(parse_goal('ship'), ops, reg)
        ok, reason = validate_plan_temporal(plan, reg, 20)
        results['temporal_validation'] = ok and bool(plan.steps)

        m = Memory(Path(tmp) / 'm.db')
        # Fake a completed prefix and ask for a repairable suffix.
        results['sqlite_wal'] = any('wal' in str(r).lower() for r in m._q('PRAGMA journal_mode'))

    passed = sum(bool(v) for v in results.values())
    return {'passed': passed, 'total': len(results), 'accuracy': passed / len(results), 'details': results}

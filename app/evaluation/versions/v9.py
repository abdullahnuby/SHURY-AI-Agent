"""Deterministic V9 capability benchmark.

This is a small diagnostic harness, not a claim of general-agent intelligence.
It measures properties that are meaningful for this runtime without a model:
AND/OR choice, recursive preconditions, unsat detection, scheduling, and memory hierarchy.
"""
from pathlib import Path
from tempfile import TemporaryDirectory

from app.runtime.registry import Tool
from app.domain.operators import build_operators
from app.domain.goal import parse_goal
from app.planning.hierarchical import hierarchical_plan
from app.planning.scheduler import critical_path
from app.domain.plan import Plan, PlanStep
from app.knowledge.memory import Memory


def run_v9_benchmark() -> dict:
    results = {}
    with TemporaryDirectory() as tmp:
        reg = {}
        reg['a'] = Tool('a', 'a', {}, lambda: 'a', match=lambda g: g == 'goal-v9',
                        produces=('done',), cost=1.0)
        reg['b'] = Tool('b', 'b', {}, lambda: 'b', match=lambda g: g == 'goal-v9',
                        produces=('done',), cost=4.0)
        plan = hierarchical_plan(parse_goal('goal-v9'), build_operators(reg), reg)
        results['alternative_selection'] = [s.tool for s in plan.steps] == ['a']

        reg2 = {
            'seed': Tool('seed', 'seed', {}, lambda: 's', match=lambda g: False, produces=('seeded',), cost=1.0),
            'prep': Tool('prep', 'prep', {}, lambda: 'p', match=lambda g: False,
                         preconditions=('seeded',), produces=('prepared',), cost=1.0),
            'finish': Tool('finish', 'finish', {}, lambda: 'f', match=lambda g: g == 'finish',
                           preconditions=('prepared',), produces=('done',), cost=1.0),
        }
        plan2 = hierarchical_plan(parse_goal('finish'), build_operators(reg2), reg2)
        results['recursive_preconditions'] = [s.tool for s in plan2.steps] == ['seed', 'prep', 'finish']

        reg3 = {
            'blocked': Tool('blocked', 'blocked', {}, lambda: 'x', match=lambda g: g == 'unsat',
                            preconditions=('never',), produces=('x',), cost=1.0),
        }
        plan3 = hierarchical_plan(parse_goal('unsat'), build_operators(reg3), reg3)
        results['unsat_abstention'] = (not plan3.steps) and bool(plan3.diagnostics['unsatisfied_facts'])

        sched_reg = {
            'x': Tool('x', 'x', {}, lambda: 'x', duration=2.0, parallel_safe=True),
            'y': Tool('y', 'y', {}, lambda: 'y', duration=3.0, parallel_safe=True),
        }
        results['critical_path'] = critical_path(Plan([PlanStep('s1', 'x', {}), PlanStep('s2', 'y', {})]), sched_reg) == 3.0

        m = Memory(Path(tmp) / 'm.db')
        m.add_note('مشروع نخيل')
        results['temporal_memory'] = len(m.recall_context('نخيل')['temporal']['L1_evidence']) == 1

    passed = sum(bool(v) for v in results.values())
    return {'passed': passed, 'total': len(results), 'accuracy': passed / len(results), 'details': results}

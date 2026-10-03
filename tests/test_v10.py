from pathlib import Path
from app.knowledge.memory import Memory, configure
from app.runtime.registry import Tool, register, REGISTRY
from app.runtime.agent import run_agent
from app.planning.planner import RulePlanner
from app.domain.plan import Plan, PlanStep
from app.planning.stn import validate_plan_temporal
from app.planning.algorithms import bayes_estimate, expected_plan_failure, relaxed_fact_costs, clause_relaxed_cost
from app.domain.goal import parse_goal
from app.domain.operators import build_operators
from app.planning.hierarchical import hierarchical_plan
from app.evaluation.versions.v10 import run_v10_benchmark


def _cleanup(*names):
    for n in names:
        REGISTRY.pop(n, None)


def test_v10_risk_aware_repair_prefers_reliable_fallback(tmp_path):
    configure(tmp_path / 'm.db')
    calls = []

    def primary():
        calls.append('primary')
        raise RuntimeError('down')

    def fallback():
        calls.append('fallback')
        return 'ok'

    register(Tool('primary_v10', 'primary', {}, primary, triggers=('recover-v10',), capability='recover', produces=('done-v10',), cost=1.0, retries=0))
    register(Tool('fallback_v10', 'fallback', {}, fallback, triggers=('recover-v10',), capability='recover', produces=('done-v10',), cost=2.0, retries=0))
    try:
        state = run_agent('recover-v10', max_replans=2)
        assert state.status == 'completed'
        assert state.replans == 1
        assert state.plan.steps[0].tool == 'fallback_v10'
        assert calls == ['primary', 'fallback']
    finally:
        _cleanup('primary_v10', 'fallback_v10')


def test_v10_stn_rejects_impossible_horizon(tmp_path):
    reg = {
        'slow_v10': Tool('slow_v10', 'slow', {}, lambda: 'x', duration=10.0),
    }
    p = Plan([PlanStep('s1', 'slow_v10', {})])
    ok, reason = validate_plan_temporal(p, reg, 5.0)
    assert not ok
    assert 'exceeds horizon' in reason or 'inconsistent' in reason


def test_v10_bayesian_reliability_conservative():
    fresh = bayes_estimate(0, 0)
    seasoned = bayes_estimate(100, 95)
    assert fresh.mean == 0.5
    assert seasoned.lower_bound > fresh.lower_bound
    assert 0.0 < expected_plan_failure([0.1, 0.2]) < 1.0


def test_v10_relaxed_heuristic_finds_recursive_cost(tmp_path):
    reg = {
        'seed_v10': Tool('seed_v10', 'seed', {}, lambda: 's', produces=('seeded-v10',), cost=1.0),
        'finish_v10': Tool('finish_v10', 'finish', {}, lambda: 'f', match=lambda g: g == 'finish-v10',
                           preconditions=('seeded-v10',), produces=('done-v10',), cost=2.0),
    }
    ops = build_operators(reg)
    costs = relaxed_fact_costs(ops, set())
    assert clause_relaxed_cost('finish-v10', ops, costs) < float('inf')
    plan = hierarchical_plan(parse_goal('finish-v10'), ops, reg)
    assert [s.tool for s in plan.steps] == ['seed_v10', 'finish_v10']


def test_v10_benchmark_green():
    result = run_v10_benchmark()
    assert result['passed'] == result['total'] == 5


def test_v10_plan_certificate_validates_state_transitions(tmp_path):
    from app.runtime.certificate import certify_plan
    reg = {
        'seed_cert': Tool('seed_cert', 'seed', {}, lambda: 's', produces=('ready-cert',), cost=1.0),
        'finish_cert': Tool('finish_cert', 'finish', {}, lambda: 'f', match=lambda g: g == 'finish-cert',
                            preconditions=('ready-cert',), produces=('done-cert',), cost=1.0),
    }
    ops = build_operators(reg)
    plan = hierarchical_plan(parse_goal('finish-cert'), ops, reg)
    cert = certify_plan(plan, reg)
    assert cert.ok
    assert 'done-cert' in cert.final_facts


def test_v10_plan_certificate_rejects_missing_precondition():
    from app.runtime.certificate import certify_plan
    reg = {'x_cert': Tool('x_cert', 'x', {}, lambda: 'x', preconditions=('missing-cert',), produces=('x',))}
    plan = Plan([PlanStep('s1', 'x_cert', {}, clause_index=-1)])
    cert = certify_plan(plan, reg)
    assert not cert.ok
    assert any('missing_preconditions' in e for e in cert.errors)


def test_v10_portfolio_is_available_and_certified(tmp_path):
    configure(tmp_path / 'm.db')
    plan = RulePlanner().plan('احسب 3*4')
    assert plan.steps
    assert plan.planner == 'v10-portfolio'
    assert plan.diagnostics['portfolio']['certified'] is True


def test_v10_posterior_reliability_is_smoothed(tmp_path):
    m = Memory(tmp_path / 'm.db')
    assert m.tool_reliability_posterior('new-tool') == 0.5
    for _ in range(3):
        m.record_tool_outcome('unstable', False)
    assert 0.0 < m.tool_reliability_posterior('unstable') < 0.5

import time
from app.knowledge.memory import Memory, configure
from app.domain.plan import PlanStep, Plan, validate
from app.runtime.registry import Tool, register, REGISTRY
from app.planning.planner import RulePlanner
from app.runtime.agent import plan_only, run_agent
from app.planning.scheduler import critical_path, schedule


def _cleanup(*names):
    for name in names:
        REGISTRY.pop(name, None)


def test_and_or_planner_chooses_lower_actual_cost(tmp_path):
    configure(tmp_path / 'm.db')
    register(Tool('cheap_v9', 'cheap', {}, lambda: 'cheap', match=lambda g: g == 'doit-v9',
                  capability='do', produces=('done_v9',), cost=1.0, risk='low'))
    register(Tool('expensive_v9', 'expensive', {}, lambda: 'expensive', match=lambda g: g == 'doit-v9',
                  capability='do', produces=('done_v9',), cost=4.0, risk='low'))
    try:
        plan, errors = plan_only('doit-v9')
        assert not errors
        assert [s.tool for s in plan.steps] == ['cheap_v9']
        assert plan.diagnostics['algorithm'] == 'hierarchical-and-or-v9'
        assert plan.diagnostics['alternative_operator_count'] >= 1
    finally:
        _cleanup('cheap_v9', 'expensive_v9')


def test_recursive_preconditions_are_solved_to_fixed_point(tmp_path):
    configure(tmp_path / 'm.db')
    register(Tool('seed_v9', 'seed', {}, lambda: 'seeded', match=lambda g: False,
                  produces=('seeded_v9',), cost=1.0))
    register(Tool('prepare_v9', 'prepare', {}, lambda: 'prepared', match=lambda g: False,
                  preconditions=('seeded_v9',), produces=('prepared_v9',), cost=1.0))
    register(Tool('finish_v9', 'finish', {}, lambda: 'done', match=lambda g: g == 'finish-v9',
                  preconditions=('prepared_v9',), produces=('goal_v9',), cost=1.0))
    try:
        plan, errors = plan_only('finish-v9')
        assert not errors
        assert [s.tool for s in plan.steps] == ['seed_v9', 'prepare_v9', 'finish_v9']
        assert plan.steps[2].depends_on == ['s2']
    finally:
        _cleanup('seed_v9', 'prepare_v9', 'finish_v9')


def test_and_group_can_reorder_for_lower_cost(tmp_path):
    configure(tmp_path / 'm.db')
    register(Tool('a_v9', 'a', {}, lambda: 'a', triggers=('alpha-v9',), produces=('a_done_v9',), cost=1.0))
    register(Tool('b_v9', 'b', {}, lambda: 'b', triggers=('beta-v9',), produces=('b_done_v9',), cost=1.0,
                  preconditions=('a_done_v9',), duration=1.0))
    register(Tool('c_v9', 'c', {}, lambda: 'c', triggers=('gamma-v9',), produces=('c_done_v9',), cost=1.0,
                  duration=10.0))
    try:
        plan, errors = plan_only('gamma-v9 و alpha-v9 و beta-v9')
        assert not errors
        assert set(s.tool for s in plan.steps) == {'a_v9', 'b_v9', 'c_v9'}
        assert [s.tool for s in plan.steps].index('a_v9') < [s.tool for s in plan.steps].index('b_v9')
    finally:
        _cleanup('a_v9', 'b_v9', 'c_v9')


def test_critical_path_is_less_than_serial_sum_for_independent_steps():
    reg = {
        'a': Tool('a', 'a', {}, lambda: 'a', duration=2.0, parallel_safe=True),
        'b': Tool('b', 'b', {}, lambda: 'b', duration=3.0, parallel_safe=True),
    }
    p = Plan([PlanStep('s1', 'a', {}), PlanStep('s2', 'b', {})])
    assert critical_path(p, reg) == 3.0


def test_exclusive_resource_forces_serial_schedule():
    reg = {
        'a': Tool('a', 'a', {}, lambda: 'a', duration=2.0, parallel_safe=True, exclusive_resources=('db',)),
        'b': Tool('b', 'b', {}, lambda: 'b', duration=3.0, parallel_safe=True, exclusive_resources=('db',)),
    }
    p = Plan([PlanStep('s1', 'a', {}), PlanStep('s2', 'b', {})])
    slots, makespan, errors = schedule(p, reg)
    assert not errors and makespan == 5.0
    assert slots[1].start == 2.0


def test_unsolvable_goal_fails_closed_and_reports_missing_fact(tmp_path):
    configure(tmp_path / 'm.db')
    register(Tool('needs_missing_v9', 'needs missing', {}, lambda: 'x', triggers=('impossible-v9',),
                  preconditions=('never_produced_v9',), produces=('x_v9',), cost=1.0))
    try:
        plan, errors = plan_only('impossible-v9')
        assert not errors
        assert plan.steps == []
        assert plan.diagnostics['unsatisfied_facts']
        assert 'never_produced_v9' in plan.diagnostics['unsatisfied_facts']
    finally:
        _cleanup('needs_missing_v9')


def test_plan_validation_rejects_future_dependency():
    reg = {
        'a': Tool('a', 'a', {}, lambda: 'a'),
        'b': Tool('b', 'b', {}, lambda: 'b'),
    }
    p = Plan([PlanStep('s1', 'a', {}, depends_on=['s2']), PlanStep('s2', 'b', {})])
    assert any('dependency s2 ليست خطوة سابقة' in e for e in validate(p, reg))


def test_v9_cli_pipeline_still_executes(tmp_path):
    configure(tmp_path / 'm.db')
    seen = []
    state = run_agent('احسب 9*7 ثم احفظ النتيجة', approve=lambda t, a: seen.append((t, a)) or True)
    assert state.status == 'completed'
    assert seen == [('save_note', {'text': '9*7 = 63'})]


def test_temporal_memory_has_five_provenance_levels(tmp_path):
    m = Memory(tmp_path / 'm.db')
    m.add_note('اجتماع مشروع نخيل', importance=5)
    m.add_note('قرار المشروع استخدام SQLite', importance=4)
    tree = m.recall_context('مشروع')['temporal']
    assert all(k in tree for k in ('L1_evidence', 'L2', 'L3', 'L4', 'L5'))
    assert tree['L1_evidence']
    assert tree['L1_evidence'][0]['source_id'].startswith(('note:', 'run:'))
    assert tree['L2'][0]['sources']


def test_routine_discovery_is_conservative(tmp_path):
    m = Memory(tmp_path / 'm.db')
    # Inject realistic completed historical runs without scheduling anything.
    for i in range(3):
        ts = f'2026-09-{20+i:02d}T09:00:00'
        m._q('INSERT INTO runs(goal,status,plan,message,ts) VALUES(?,?,?,?,?)',
             ('احسب 2+2', 'completed', '{"steps":[]}', 'done', ts))
    routines = m.routine_candidates(min_occurrences=3, days=30)
    assert routines and routines[0]['action'] == 'candidate_routine'
    assert routines[0]['occurrences'] == 3


def test_v9_capability_benchmark_is_green():
    from app.evaluation.versions.v9 import run_v9_benchmark
    result = run_v9_benchmark()
    assert result['passed'] == result['total'] == 5

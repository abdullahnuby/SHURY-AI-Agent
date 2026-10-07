from __future__ import annotations

import threading
import time

from app.brain.kernel import CognitiveKernel
from app.brain.models import CognitiveState, PlannedAction
from app.organization import DEFAULT_COMPANY
from app.organization.scheduler import CompanyScheduler
from app.runtime.registry import Tool


def _assignment_step(step_id: str, tool: Tool, depends=()):
    action = PlannedAction(
        step_id, 'data analysis', tool.name, {},
        skill_key='builtin:data-analysis', capability='data-analysis', depends_on=tuple(depends),
    )
    return action


def test_scheduler_packs_independent_parallel_safe_tasks():
    kernel = CognitiveKernel()
    actions = [
        PlannedAction('s1', 'a', 'analyze_dataset', {}),
        PlannedAction('s2', 'b', 'profile_dataset', {}),
    ]
    assignments = DEFAULT_COMPANY.route_plan('parallel', actions, tool_registry=kernel.registry)
    coordination = DEFAULT_COMPANY.coordinate('parallel', assignments, tool_registry=kernel.registry)
    schedule = coordination.execution_schedule
    assert schedule
    assert any(row['mode'] == 'parallel' and len(row['task_ids']) == 2 for row in schedule)
    assert coordination.schedule_estimated_duration < coordination.schedule_serial_duration


def test_scheduler_keeps_approval_gated_task_serial():
    safe = Tool(
        name='safe_parallel', description='safe', params={}, fn=lambda: {'ok': True},
        capability='data-analysis', organization_department='data', organization_role='data:data-analyst',
        parallel_safe=True, duration=1.0,
    )
    gated = Tool(
        name='approval_parallel', description='gated', params={}, fn=lambda: {'ok': True},
        capability='data-analysis', organization_department='data', organization_role='data:data-analyst',
        parallel_safe=True, requires_approval=True, duration=1.0,
    )
    scheduler = CompanyScheduler()
    from app.organization.models import CompanyTask, ExecutionWave
    tasks = [
        CompanyTask('company:s1', 'a', 'data', 'data:head', 'data:data-analyst', 's1', safe.name, capability='data-analysis'),
        CompanyTask('company:s2', 'b', 'data', 'data:head', 'data:data-analyst', 's2', gated.name, capability='data-analysis'),
    ]
    schedule = scheduler.schedule(tasks, (ExecutionWave(1, ('company:s1', 'company:s2')),), {safe.name: safe, gated.name: gated})
    assert any(row.mode == 'serial' and row.task_ids == ('company:s2',) and row.reason == 'approval_gated' for row in schedule.batches)
    assert any(row.mode == 'serial' and row.task_ids == ('company:s1',) for row in schedule.batches)


def test_parallel_batch_runs_tool_calls_concurrently():
    barrier = threading.Barrier(2)
    starts = {}

    def fn(name):
        starts[name] = time.monotonic()
        barrier.wait(timeout=2)
        time.sleep(0.08)
        return {'name': name}

    tools = {
        'parallel_a': Tool(
            name='parallel_a', description='a', params={}, fn=lambda: fn('a'),
            capability='data-analysis', organization_department='data', organization_role='data:data-analyst',
            parallel_safe=True, duration=0.1,
        ),
        'parallel_b': Tool(
            name='parallel_b', description='b', params={}, fn=lambda: fn('b'),
            capability='data-analysis', organization_department='data', organization_role='data:data-analyst',
            parallel_safe=True, duration=0.1,
        ),
    }
    kernel = CognitiveKernel(registry=tools)
    state = CognitiveState('parallel')
    actions = [
        PlannedAction('s1', 'data-analysis', 'parallel_a', {}, skill_key='builtin:data-analysis'),
        PlannedAction('s2', 'data-analysis', 'parallel_b', {}, skill_key='builtin:data-analysis'),
    ]
    assignments = DEFAULT_COMPANY.route_plan('parallel', actions, tool_registry=tools)
    state.company_assignments = [a.to_dict() for a in assignments]
    state.company_coordination = DEFAULT_COMPANY.coordinate('parallel', assignments, tool_registry=tools).to_dict()
    outputs = {}
    started = time.monotonic()
    results = kernel._run_company_parallel_batch(state, tuple(actions), outputs, lambda _t, _a: True)
    elapsed = time.monotonic() - started
    assert all(item[2][0] and item[2][3] for item in results)
    assert set(item[2][1]['name'] for item in results) == {'a', 'b'}
    assert abs(starts['a'] - starts['b']) < 0.05
    assert elapsed < 0.30


def test_canonical_execute_result_uses_parallel_scheduler(monkeypatch, tmp_path):
    from app.brain.kernel import BrainResult
    from app.brain.models import Decision, GoalSpec
    from app.knowledge.memory import Memory
    from app.brain.store import BrainStateStore
    from app.learning.store import LearningStore

    starts = {}

    def make_fn(name):
        def fn():
            starts[name] = time.monotonic()
            time.sleep(0.05)
            return {"name": name}
        return fn

    tools = {
        'parallel_c': Tool(
            name='parallel_c', description='c', params={}, fn=make_fn('c'),
            capability='data-analysis', organization_department='data', organization_role='data:data-analyst',
            parallel_safe=True, duration=0.1,
        ),
        'parallel_d': Tool(
            name='parallel_d', description='d', params={}, fn=make_fn('d'),
            capability='data-analysis', organization_department='data', organization_role='data:data-analyst',
            parallel_safe=True, duration=0.1,
        ),
    }
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / 'memory.db'),
        registry=tools,
        state_store=BrainStateStore(tmp_path / 'state.db'),
        experience_store=LearningStore(tmp_path / 'exp.db'),
    )
    state = CognitiveState('parallel canonical', session_id='parallel-canonical')
    state.goal = GoalSpec('parallel', 'run two independent analyses')
    state.decision = Decision('execute', 1.0, 'test')
    state.plan = [
        PlannedAction('s1', 'data-analysis', 'parallel_c', {}, skill_key='builtin:data-analysis'),
        PlannedAction('s2', 'data-analysis', 'parallel_d', {}, skill_key='builtin:data-analysis'),
    ]
    assignments = DEFAULT_COMPANY.route_plan('parallel', state.plan, tool_registry=tools)
    state.company_assignments = [a.to_dict() for a in assignments]
    state.company_coordination = DEFAULT_COMPANY.coordinate('parallel', assignments, tool_registry=tools).to_dict()

    result = kernel._execute_result(BrainResult(state, run_id='parallel-canonical'), approve=lambda _t, _a: True, max_steps=4)
    assert result.status == 'completed'
    assert {item['step_id'] for item in result.state.observations if item.get('ok')} >= {'s1', 's2'}
    assert any(e.get('kind') == 'company_parallel_batch_started' for e in result.state.trace)
    assert abs(starts['c'] - starts['d']) < 0.04

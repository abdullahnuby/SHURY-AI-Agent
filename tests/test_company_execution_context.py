from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.brain.kernel import CognitiveKernel
from app.brain.models import CognitiveState, PlannedAction
from app.runtime.registry import Tool
from app.organization import DEFAULT_COMPANY
from app.organization.context import CompanyContextViolation, current_company_context


def _assignment(step_id='s2', department='data', specialist='data:data-analyst', **extra):
    base = {
        'objective': 'analyze', 'operation': 'data_analysis', 'skill_key': 'builtin:data-analysis',
        'chief_executive': 'executive:chief-executive', 'department': department,
        'department_head': f'{department}:head', 'specialist': specialist,
        'reviewers': ('qa:reviewer',), 'authority': 'autonomous', 'reason': 'test',
        'step_id': step_id, 'tool': 'analyze_csv_by_average' if department == 'data' else 'list_files_recursive',
        'capability': 'data-analysis' if department == 'data' else 'workspace-recursive-inventory',
        'depends_on': ('s1',), 'expected_effects': (),
    }
    base.update(extra)
    return base


def test_task_context_is_least_privilege_and_handoff_aware():
    assignment = _assignment()
    coordination = {
        'tasks': [
            {'task_id': 'company:s1', 'step_id': 's1', 'department': 'operations'},
            {'task_id': 'company:s2', 'step_id': 's2', 'department': 'data'},
        ],
        'handoffs': [{
            'handoff_id': 'handoff:company:s1->s2', 'from_task': 'company:s1', 'to_task': 'company:s2',
            'contract': ['dependency-complete', 'producer-observation-available'],
        }],
    }
    context = DEFAULT_COMPANY.registry.build_execution_context(
        assignment=assignment, objective='analyze', coordination=coordination,
        arg_keys=('file_list', 'question'), tool_registry={},
    )
    assert context.department == 'data'
    assert context.specialist == 'data:data-analyst'
    assert context.allowed_tools == ('analyze_csv_by_average',)
    assert context.dependency_steps == ('s1',)
    assert 'handoff:company:s1->s2' in context.inbound_handoffs
    assert 'dependency:s1' in context.allowed_input_refs
    assert context.allowed_artifact_refs == ('output:s1',)
    assert context.memory_policy == 'task_local_only'


def test_undeclared_dependency_reference_is_blocked_before_tool_execution():
    kernel = CognitiveKernel()
    state = CognitiveState('analyze')
    state.plan = [PlannedAction('s2', 'data-analysis', 'analyze_csv_by_average', args={'file_list': '{{s1}}'}, depends_on=())]
    assignment = DEFAULT_COMPANY.route_plan('analyze', state.plan, tool_registry=kernel.registry)[0]
    state.company_assignments = [assignment.to_dict()]
    state.company_coordination = DEFAULT_COMPANY.coordinate('analyze', state.plan, tool_registry=kernel.registry).to_dict()
    called = {'value': False}

    def fake_run(**kwargs):
        called['value'] = True
        return {'ok': True}

    original = kernel.registry['analyze_csv_by_average'].fn
    kernel.registry['analyze_csv_by_average'].fn = fake_run
    try:
        ok, _, error, executed, _ = kernel._run_action(state, state.plan[0], {'s1': {'secret': 'not allowed'}}, lambda _t, _a: True)
    finally:
        kernel.registry['analyze_csv_by_average'].fn = original
    assert ok is False
    assert executed is False
    assert called['value'] is False
    assert 'undeclared dependency' in error
    assert state.trace[-1]['kind'] == 'company_context_violation'


def test_declared_dependency_reference_is_available_inside_task_context():
    seen = {}
    def fake_tool(**kwargs):
        context = current_company_context()
        seen['context_id'] = context.context_id if context else None
        seen['department'] = context.department if context else None
        seen['kwargs'] = kwargs
        return {'value': 42}

    tool = Tool(
        name='context_probe', description='probe', params={'input_value': 'object'}, fn=fake_tool,
        capability='data-analysis', organization_department='data', organization_role='data:data-analyst',
        produces=('probe_done',),
    )
    kernel = CognitiveKernel(registry={'context_probe': tool})
    state = CognitiveState('probe')
    action = PlannedAction('s2', 'data-analysis', 'context_probe', args={'input_value': '{{s1}}'}, depends_on=('s1',))
    assignment = DEFAULT_COMPANY.route_plan('probe', [action], tool_registry=kernel.registry)[0]
    state.plan = [action]
    state.company_assignments = [assignment.to_dict()]
    state.company_coordination = DEFAULT_COMPANY.coordinate('probe', [assignment], tool_registry=kernel.registry).to_dict()
    ok, output, error, executed, _ = kernel._run_action(state, action, {'s1': {'allowed': 'yes'}}, lambda _t, _a: True)
    assert ok is True
    assert executed is True
    assert error is None
    assert output == {'value': 42}
    assert seen['department'] == 'data'
    assert seen['kwargs']['input_value'] == {'allowed': 'yes'}
    assert current_company_context() is None


def test_company_context_is_task_scoped_and_does_not_carry_unrelated_outputs():
    coordination = DEFAULT_COMPANY.coordinate(
        'cross department',
        [
            PlannedAction('s1', 'workspace-recursive-inventory', 'list_files_recursive'),
            PlannedAction('s2', 'data-analysis', 'analyze_csv_by_average', args={'file_list': '{{s1}}'}, depends_on=('s1',)),
            PlannedAction('s3', 'data-analysis', 'analyze_csv_by_average', args={'file_list': 'literal'}, depends_on=()),
        ],
        tool_registry=CognitiveKernel().registry,
    )
    assignments = DEFAULT_COMPANY.route_plan(
        'cross department',
        [
            PlannedAction('s1', 'workspace-recursive-inventory', 'list_files_recursive'),
            PlannedAction('s2', 'data-analysis', 'analyze_csv_by_average', args={'file_list': '{{s1}}'}, depends_on=('s1',)),
            PlannedAction('s3', 'data-analysis', 'analyze_csv_by_average', args={'file_list': 'literal'}, depends_on=()),
        ],
        tool_registry=CognitiveKernel().registry,
    )
    ctx_s3 = DEFAULT_COMPANY.registry.build_execution_context(
        assignment=assignments[2], objective='cross department', coordination=coordination.to_dict(), arg_keys=('file_list',), tool_registry={}
    )
    assert ctx_s3.dependency_steps == ()
    assert 'dependency:s1' not in ctx_s3.allowed_input_refs
    assert ctx_s3.inbound_handoffs == ()
    with pytest.raises(CompanyContextViolation):
        from app.organization.context import assert_references_allowed
        assert_references_allowed('{{s1}}', ctx_s3)


def test_context_metadata_round_trips_through_cognitive_state():
    state = CognitiveState('context serialization')
    state.company_active_context = {'task_id': 'company:s1', 'department': 'operations'}
    state.company_execution_contexts = {'company:s1': state.company_active_context}
    data = state.to_dict()
    assert data['company_active_context']['department'] == 'operations'
    assert data['company_execution_contexts']['company:s1']['task_id'] == 'company:s1'

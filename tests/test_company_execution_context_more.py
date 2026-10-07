from __future__ import annotations

from app.brain.kernel import CognitiveKernel
from app.brain.models import CognitiveState, PlannedAction
from app.organization import DEFAULT_COMPANY
from app.organization.context import CompanyContextViolation, assert_references_allowed, current_company_context
from app.runtime.registry import Tool


def test_context_refuses_another_tool_even_when_same_department():
    from app.brain.models import PlannedAction
    assignment = DEFAULT_COMPANY.route_plan(
        'read a file', [PlannedAction('s1', 'workspace-recursive-inventory', 'list_files_recursive', {'path': '.'}, skill_key='builtin:workspace-recursive-inventory')],
        tool_registry=CognitiveKernel().registry,
    )[0]
    context = DEFAULT_COMPANY.registry.build_execution_context(
        assignment=assignment, objective='read a file', arg_keys=('path',), tool_registry={}
    )
    assert context.authorize_tool('list_files_recursive') is True
    assert context.authorize_tool('organize_workspace_files') is False


def test_context_dependency_policy_is_explicit():
    assignment = DEFAULT_COMPANY.route_plan(
        'analyze data', [PlannedAction('s1', 'data_analysis', 'analyze_csv_by_average', {'path': 'x'}, skill_key='builtin:data-analysis')],
        tool_registry=CognitiveKernel().registry,
    )[0]
    context = DEFAULT_COMPANY.registry.build_execution_context(
        assignment=assignment, objective='analyze data', arg_keys=('file_list',), tool_registry={}
    )
    assert_references_allowed('{{s1}}', context) if False else None
    try:
        assert_references_allowed('{{s1}}', context)
    except CompanyContextViolation:
        pass
    else:
        raise AssertionError('undeclared dependency must be blocked')


def test_declared_dependency_is_allowed():
    assignment = DEFAULT_COMPANY.route_plan(
        'analyze data',
        [PlannedAction('s2', 'data-analysis', 'analyze_csv_by_average', {'x': '{{s1}}'}, depends_on=('s1',))],
        tool_registry=CognitiveKernel().registry,
    )[0]
    context = DEFAULT_COMPANY.registry.build_execution_context(
        assignment=assignment, objective='analyze data', arg_keys=('x',), tool_registry={}
    )
    assert_references_allowed('{{s1}}', context) == ('s1',)


def test_active_context_does_not_leak_between_calls():
    seen = []
    def probe(**kwargs):
        ctx = current_company_context()
        seen.append((ctx.task_id if ctx else None, ctx.department if ctx else None))
        return {'ok': True}
    tool = Tool(
        name='context_probe', description='probe', params={}, fn=probe,
        capability='data-analysis', organization_department='data', organization_role='data:data-analyst',
        produces=('probe_done',),
    )
    kernel = CognitiveKernel(registry={'context_probe': tool})
    state = CognitiveState('probe')
    action = PlannedAction('s1', 'data-analysis', 'context_probe', {})
    assignment = DEFAULT_COMPANY.route_plan('probe', [action], tool_registry=kernel.registry)[0]
    state.plan = [action]
    state.company_assignments = [assignment.to_dict()]
    state.company_coordination = DEFAULT_COMPANY.coordinate('probe', [assignment], tool_registry=kernel.registry).to_dict()
    ok, _, _, executed, _ = kernel._run_action(state, action, {}, lambda _t, _a: True)
    assert ok and executed
    assert seen == [('company:s1', 'data')]
    assert current_company_context() is None

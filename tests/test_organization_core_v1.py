from types import SimpleNamespace

import pytest

from app.organization import DEFAULT_COMPANY, OrganizationRoutingError
from app.runtime.registry import load_tools
from app.brain.models import CognitiveState, PlannedAction


def test_all_current_builtin_skills_have_one_department_owner():
    known = {
        'builtin:calculate', 'builtin:time', 'builtin:remember', 'builtin:forget',
        'builtin:identity-recall', 'builtin:memory-search', 'builtin:workspace-file-organization',
        'builtin:workspace-duplicate-cleanup', 'builtin:workspace-recursive-inventory',
        'builtin:workspace-inventory', 'builtin:file-read', 'builtin:data-analysis',
        'builtin:data-analysis-report', 'builtin:project-inspection', 'builtin:project-validation',
        'builtin:web-research', 'builtin:research-report', 'builtin:project-audit',
    }
    owners = {key: DEFAULT_COMPANY.discover_skill_owner(key) for key in known}
    assert all(owners.values())
    assert len(set(owners.values())) >= 4


def test_route_uses_structured_tool_ownership_not_tool_name_map():
    registry = dict(load_tools())
    custom = SimpleNamespace(
        step_id='s1', tool='future_custom_data_tool', capability='future_capability',
        skill_key='', depends_on=(), expected_effects=(),
    )
    registry['future_custom_data_tool'] = SimpleNamespace(
        name='future_custom_data_tool', organization_department='data', organization_role='data:data-analyst',
        capability='future_capability', risk='low', produces=('future_data_artifact',),
    )
    assignments = DEFAULT_COMPANY.route_plan('future capability', [custom], tool_registry=registry)
    assert assignments[0].department == 'data'
    assert assignments[0].specialist == 'data:data-analyst'


def test_route_fails_closed_for_unknown_capability():
    step = SimpleNamespace(step_id='s1', tool='unknown_tool', capability='unknown_capability', skill_key='', depends_on=(), expected_effects=())
    with pytest.raises(OrganizationRoutingError):
        DEFAULT_COMPANY.route_plan('unknown', [step], tool_registry={})


def test_cross_department_coordination_creates_explicit_handoff():
    plan = [
        PlannedAction('s1', 'workspace-recursive-inventory', 'list_files_recursive'),
        PlannedAction('s2', 'data-analysis', 'analyze_csv_collection', depends_on=('s1',)),
        PlannedAction('s3', 'workspace-movement', 'move_workspace_report', depends_on=('s2',)),
    ]
    coordination = DEFAULT_COMPANY.coordinate('cross department job', plan, tool_registry=load_tools())
    assert [task.department for task in coordination.tasks] == ['operations', 'data', 'operations']
    assert len(coordination.handoffs) == 2
    assert coordination.handoffs[0].producer_department == 'operations'
    assert coordination.handoffs[0].consumer_department == 'data'
    assert coordination.handoffs[1].producer_department == 'data'
    assert coordination.handoffs[1].consumer_department == 'operations'


def test_company_state_serializes_coordination():
    state = CognitiveState('test')
    state.company_coordination = {'company': 'SHURY Company', 'version': 1, 'tasks': [], 'handoffs': []}
    assert state.to_dict()['company_coordination']['company'] == 'SHURY Company'


def test_tool_manifest_exposes_organizational_metadata():
    tool = load_tools()['analyze_csv_by_average']
    manifest = tool.manifest()
    assert manifest['organization_department'] == 'data'
    assert manifest['organization_role'] == 'data:data-analyst'


def test_company_has_no_legacy_tool_department_mapping():
    source = open('app/organization/company.py', encoding='utf-8').read()
    assert '_OPERATION_DEPARTMENT' not in source
    assert '_SKILL_TO_DEPARTMENT' not in source
    assert 'tool_department = {' not in source


def test_company_coordinate_rejects_tampered_department_before_execution():
    from app.brain import CognitiveKernel
    kernel = CognitiveKernel()
    payload = {
        'goal': 'analyze dataset', 'operation': 'data_analysis', 'capability': 'data_analysis',
        'target': '', 'target_type': '', 'slots': {'path': 'workspace/sales.csv'},
        'constraints': [], 'temporal_requirements': [], 'required_evidence': [],
        'priority': 0.5, 'language': 'en',
    }
    result = kernel.think_structured(payload)
    assert result.state.company_assignments
    result.state.company_assignments[0]['department'] = 'operations'
    step = result.state.plan[0]
    ok, _, error, executed, _ = kernel._run_action(result.state, step, {}, lambda _t, _a: True)
    assert ok is False
    assert executed is False
    assert 'تفويض' in str(error) or 'مالك' in str(error)

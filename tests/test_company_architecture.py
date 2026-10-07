from app.organization import DEFAULT_COMPANY


def test_company_roster_is_valid():
    result = DEFAULT_COMPANY.validate()
    assert result.valid, result.errors


def test_every_current_builtin_skill_has_an_owner():
    known = {
        'builtin:calculate', 'builtin:time', 'builtin:remember', 'builtin:forget',
        'builtin:identity-recall', 'builtin:memory-search', 'builtin:workspace-file-organization',
        'builtin:workspace-duplicate-cleanup', 'builtin:workspace-recursive-inventory',
        'builtin:workspace-inventory', 'builtin:file-read', 'builtin:data-analysis',
        'builtin:data-analysis-report', 'builtin:project-inspection', 'builtin:project-validation',
        'builtin:web-research', 'builtin:research-report', 'builtin:project-audit',
    }
    unowned = sorted(key for key in known if DEFAULT_COMPANY.discover_skill_owner(key) is None)
    assert unowned == []


def test_route_data_to_data_department():
    assignment = DEFAULT_COMPANY.route('analyze the dataset', 'data_analysis', 'builtin:data-analysis')
    assert assignment.department == 'data'
    assert assignment.department_head == 'data:head'
    assert assignment.specialist == 'data:data-analyst'
    assert 'qa:reviewer' in assignment.reviewers


def test_route_file_action_to_operations_department():
    assignment = DEFAULT_COMPANY.route('organize workspace files', 'workspace_file_organization', 'builtin:workspace-file-organization')
    assert assignment.department == 'operations'
    assert assignment.specialist == 'operations:file-specialist'


def test_security_reviewer_is_added_for_medium_or_high_risk():
    assignment = DEFAULT_COMPANY.route('change an external resource', 'project_task', 'builtin:project-audit', risk='high')
    assert assignment.reviewers[0] == 'security:reviewer'
    assert 'qa:reviewer' in assignment.reviewers


def test_ceo_can_issue_a_scoped_execution_mandate():
    assignment = DEFAULT_COMPANY.route('organize workspace files', 'workspace_file_organization', 'builtin:workspace-file-organization')
    mandate = DEFAULT_COMPANY.mandate(assignment, 'builtin:workspace-file-organization')
    assert mandate.authorize('builtin:workspace-file-organization', 'operations')
    assert not mandate.authorize('builtin:data-analysis', 'data')


def test_wrong_department_cannot_claim_a_skill():
    # Use the public route for a real operations assignment, then attempt to claim a data skill.
    operations = DEFAULT_COMPANY.route('organize files', 'workspace_file_organization', 'builtin:workspace-file-organization')
    try:
        DEFAULT_COMPANY.mandate(operations, 'builtin:data-analysis')
    except PermissionError:
        return
    raise AssertionError('cross-department skill claim was not rejected')

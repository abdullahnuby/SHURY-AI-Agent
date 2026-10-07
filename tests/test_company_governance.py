from types import SimpleNamespace

from app.organization import DEFAULT_COMPANY, CompanyGovernance, GovernanceContext


def _tool(**overrides):
    base = dict(
        name='test-tool', risk='low', requires_approval=False, removes=(), produces=(),
        governance_class=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _assignment(**overrides):
    base = dict(
        chief_executive='executive:chief-executive', department='operations',
        specialist='operations:file-specialist', skill_key='builtin:file-read',
        capability='file_read', reviewers=('qa:reviewer',), authority='autonomous',
    )
    base.update(overrides)
    return base


def _context(**overrides):
    base = dict(
        task_id='s1', department='operations', specialist='operations:file-specialist',
        skill_key='builtin:file-read', capability='file_read',
    )
    base.update(overrides)
    return GovernanceContext(**base)


def test_low_risk_autonomous_action_is_allowed_without_approval():
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(_assignment(), _tool(), _context(), {'path': 'x'})
    assert decision.allowed is True
    assert decision.decision == 'allow'
    assert decision.human_approval_required is False


def test_approval_required_tool_returns_bounded_approval_request():
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(
        _assignment(reviewers=('qa:reviewer', 'security:reviewer')), _tool(requires_approval=True, risk='medium'), _context(), {'path': 'x'}
    )
    assert decision.allowed is True
    assert decision.decision == 'approval_required'
    assert decision.human_approval_required is True
    assert decision.approval is not None
    assert len(decision.approval.action_fingerprint) == 64


def test_proposes_authority_requires_human_approval():
    assignment = _assignment(authority='proposes')
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(assignment, _tool(), _context(), {'path': 'x'})
    assert decision.allowed is True
    assert decision.human_approval_required is True
    assert 'assignment_authority_requires_orchestrator_approval' in decision.reasons


def test_escalates_authority_requires_human_approval():
    assignment = _assignment(authority='escalates')
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(assignment, _tool(), _context(), {'path': 'x'})
    assert decision.allowed is True
    assert decision.human_approval_required is True
    assert 'assignment_authority_is_escalation_only' in decision.reasons


def test_high_impact_action_without_security_reviewer_is_denied():
    assignment = _assignment(reviewers=('qa:reviewer',))
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(
        assignment, _tool(risk='high', requires_approval=True), _context(), {'path': 'x'}
    )
    assert decision.allowed is False
    assert 'controlled_action_requires_independent_security_reviewer' in decision.reasons


def test_high_impact_action_without_explicit_approval_contract_is_denied():
    assignment = _assignment(reviewers=('qa:reviewer', 'security:reviewer'))
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(
        assignment, _tool(risk='high', requires_approval=False), _context(), {'path': 'x'}
    )
    assert decision.allowed is False
    assert 'high_impact_tool_must_require_human_approval' in decision.reasons


def test_destructive_action_requires_human_approval():
    assignment = _assignment(reviewers=('qa:reviewer', 'security:reviewer'))
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(
        assignment, _tool(governance_class='destructive', risk='medium', requires_approval=False), _context(), {'path': 'x'}
    )
    assert decision.allowed is True
    assert decision.human_approval_required is True
    assert decision.decision == 'approval_required'


def test_external_publication_requires_human_approval():
    assignment = _assignment(reviewers=('qa:reviewer', 'security:reviewer'))
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(
        assignment, _tool(governance_class='external-publication'), _context(), {'url': 'https://example.com'}
    )
    assert decision.allowed is True
    assert decision.human_approval_required is True


def test_reviewer_cannot_execute_producer_action():
    assignment = _assignment(specialist='security:reviewer', department='security')
    context = _context(department='security', specialist='security:reviewer', skill_key='', capability='security-review')
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(assignment, _tool(), context, {})
    assert decision.allowed is False
    assert 'reviewer_cannot_execute_producer_action' in decision.reasons


def test_assignment_mismatch_is_denied_fail_closed():
    assignment = _assignment(department='data')
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(assignment, _tool(), _context(), {})
    assert decision.allowed is False
    assert 'assignment_department_mismatch' in decision.reasons


def test_action_fingerprint_changes_with_arguments():
    tool = _tool()
    gov = CompanyGovernance(DEFAULT_COMPANY)
    left = gov.action_fingerprint(task_id='s1', tool=tool, args={'path': 'a'})
    right = gov.action_fingerprint(task_id='s1', tool=tool, args={'path': 'b'})
    assert left != right


def test_governance_does_not_grant_write_authority_by_itself():
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(
        _assignment(authority='autonomous'), _tool(governance_class='read-only'), _context(), {}
    )
    assert decision.allowed is True
    assert decision.action_class == 'read-only'
    assert decision.human_approval_required is False


def test_canonical_kernel_denies_high_impact_tool_before_function_call(tmp_path):
    from app.brain.kernel import CognitiveKernel
    from app.brain.models import CognitiveState, GoalSpec, PlannedAction
    from app.knowledge.memory import Memory
    from app.learning.store import LearningStore
    from app.runtime.registry import Tool

    calls = []
    tool = Tool(
        name='governed-danger', description='test high impact action', params={'path': 'str'},
        fn=lambda path: calls.append(path), requires_approval=False, risk='high',
        capability='file_read', organization_department='operations', organization_role='operations:file-specialist',
    )
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / 'memory.db'),
        registry={tool.name: tool},
        experience_store=LearningStore(tmp_path / 'learning.db'),
    )
    action = PlannedAction('s1', 'file_read', tool.name, {'path': 'x'}, skill_key='builtin:file-read')
    state = CognitiveState('governed test', session_id='test', goal=GoalSpec('test', 'governed test'))
    assignment = DEFAULT_COMPANY.route_plan('governed test', [action], tool_registry=kernel.registry)[0]
    state.company_assignments = [assignment.to_dict()]

    ok, output, error, executed, _ = kernel._run_action(state, action, {}, lambda _t, _a: True)
    assert ok is False
    assert executed is False
    assert calls == []
    assert 'تم رفض العملية بواسطة حوكمة الشركة' in str(error)
    assert any(e.get('kind') == 'company_governance_denied' for e in state.trace)


def test_canonical_kernel_records_human_governance_approval(tmp_path, monkeypatch):
    from app.brain.kernel import CognitiveKernel
    from app.brain.models import CognitiveState, GoalSpec, PlannedAction
    from app.knowledge.memory import Memory
    from app.learning.store import LearningStore
    from app.runtime.registry import Tool
    monkeypatch.setattr('app.brain.kernel.verify_step', lambda _tool, _args, _result: (True, None))

    calls = []
    tool = Tool(
        name='governed-write', description='test controlled action', params={'path': 'str'},
        fn=lambda path: calls.append(path) or {'path': path}, requires_approval=True, risk='medium',
        capability='file_read', organization_department='operations', organization_role='operations:file-specialist',
        idempotent=True,
    )
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / 'memory.db'),
        registry={tool.name: tool},
        experience_store=LearningStore(tmp_path / 'learning.db'),
    )
    action = PlannedAction('s1', 'file_read', tool.name, {'path': 'x'}, skill_key='builtin:file-read')
    state = CognitiveState('governed approval test', session_id='test', goal=GoalSpec('test', 'governed approval test'))
    assignment = DEFAULT_COMPANY.route_plan('governed approval test', [action], tool_registry=kernel.registry)[0]
    state.company_assignments = [assignment.to_dict()]

    ok, output, error, executed, _ = kernel._run_action(state, action, {}, lambda _t, _a: True)
    assert ok is True
    assert executed is True
    assert calls == ['x']
    assert any(e.get('kind') == 'company_governance_approval_requested' for e in state.trace)
    assert any(e.get('kind') == 'company_governance_approval_granted' for e in state.trace)


def test_producer_cannot_review_own_action():
    assignment = _assignment(reviewers=('operations:file-specialist', 'qa:reviewer', 'security:reviewer'))
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(assignment, _tool(), _context(), {})
    assert decision.allowed is False
    assert 'producer_cannot_review_own_action' in decision.reasons


def test_unknown_reviewer_is_denied_fail_closed():
    assignment = _assignment(reviewers=('qa:reviewer', 'security:not-real'))
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(assignment, _tool(), _context(), {})
    assert decision.allowed is False
    assert any(x.startswith('reviewer_not_in_company_registry:') for x in decision.reasons)


def test_builder_cannot_be_used_as_independent_reviewer():
    assignment = _assignment(reviewers=('qa:reviewer', 'operations:file-specialist'))
    decision = CompanyGovernance(DEFAULT_COMPANY).evaluate(assignment, _tool(), _context(), {})
    assert decision.allowed is False
    assert any(x.startswith('reviewer_role_not_independent:') for x in decision.reasons)

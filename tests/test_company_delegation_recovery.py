from pathlib import Path

from app.brain.models import PlannedAction
from app.learning.store import LearningStore
from app.organization import DEFAULT_COMPANY
from app.organization.recovery import CompanyRecoveryManager
from app.runtime.registry import Tool, load_tools


def _tools():
    def fail():
        raise RuntimeError("primary failed")
    return {
        "primary_data": Tool(name="primary_data", description="primary", params={}, fn=fail,
            capability="recovery-analysis", organization_department="data", organization_role="data:data-analyst",
            verification_level="strong", cost=1.0),
        "backup_data": Tool(name="backup_data", description="backup", params={}, fn=lambda: {"ok": True},
            capability="recovery-analysis", organization_department="data", organization_role="data:data-analyst",
            verification_level="strong", cost=1.2),
    }


def _seed(store: LearningStore):
    return store.record_company_delegation_outcome(
        capability="recovery-analysis", department="data", specialist="data:data-analyst",
        skill_key="", tool="backup_data", verified=True, duration=0.1, run_id="seed",
    )


def test_recovery_escalates_without_verified_alternative(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    manager = CompanyRecoveryManager()
    action = PlannedAction("s1", "recovery-analysis", "primary_data", {})
    decision = manager.decide(action=action, error="primary failed", organization=DEFAULT_COMPANY.registry,
                              tool_registry=_tools(), learning_store=store)
    assert decision.decision == "escalate"
    assert decision.ownership_immutable is True


def test_recovery_redelegates_only_to_verified_same_capability(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    _seed(store)
    manager = CompanyRecoveryManager()
    action = PlannedAction("s1", "recovery-analysis", "primary_data", {})
    decision = manager.decide(action=action, error="primary failed", organization=DEFAULT_COMPANY.registry,
                              tool_registry=_tools(), learning_store=store)
    assert decision.decision == "redelegate"
    assert decision.selected.tool == "backup_data"
    assert decision.selected.capability == "recovery-analysis"
    replacement = manager.redelegate_action(action, decision, _tools())
    assert replacement is not None
    assert replacement.step_id == "s1"
    assert replacement.capability == "recovery-analysis"
    assert replacement.tool == "backup_data"


def test_recovery_never_changes_ownership_on_governance_failure(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    _seed(store)
    manager = CompanyRecoveryManager()
    action = PlannedAction("s1", "recovery-analysis", "primary_data", {})
    decision = manager.decide(action=action, error="تعذر إثبات تفويض الشركة", organization=DEFAULT_COMPANY.registry,
                              tool_registry=_tools(), learning_store=store)
    assert decision.decision == "escalate"
    assert decision.failure_class == "authorization"


def test_canonical_runtime_redelegates_failed_specialist_to_verified_alternative(tmp_path: Path):
    from app.brain.kernel import CognitiveKernel, BrainResult
    from app.brain.models import CognitiveState, Decision, GoalSpec
    from app.brain.store import BrainStateStore
    from app.knowledge.memory import Memory
    from app.learning.store import LearningStore

    def failing():
        raise RuntimeError('primary failed')

    tools = {
        'company_primary': Tool(
            name='company_primary', description='primary', params={}, fn=failing,
            capability='recovery-analysis', organization_department='data', organization_role='data:data-analyst',
            verification_level='strong', cost=1.0,
        ),
        'company_backup': Tool(
            name='company_backup', description='backup', params={}, fn=lambda: {'recovered': True},
            capability='recovery-analysis', organization_department='data', organization_role='data:data-analyst',
            verification_level='strong', cost=1.1,
        ),
    }
    learning_store = LearningStore(tmp_path / 'learning.db')
    learning_store.record_company_delegation_outcome(
        capability='recovery-analysis', department='data', specialist='data:data-analyst',
        tool='company_backup', verified=True, duration=0.01, run_id='seed',
    )
    kernel = CognitiveKernel(
        memory=Memory(tmp_path / 'memory.db'), registry=tools,
        state_store=BrainStateStore(tmp_path / 'state.db'), experience_store=learning_store,
    )
    state = CognitiveState('recover canonical', session_id='c9-canonical')
    state.goal = GoalSpec('recovery', 'recover primary analysis')
    state.decision = Decision('execute', 1.0, 'test')
    state.plan = [PlannedAction('s1', 'recovery-analysis', 'company_primary', {})]
    assignments = DEFAULT_COMPANY.route_plan('recover canonical', state.plan, tool_registry=tools)
    state.company_assignments = [a.to_dict() for a in assignments]
    state.company_coordination = DEFAULT_COMPANY.coordinate('recover canonical', assignments, tool_registry=tools).to_dict()
    result = kernel._execute_result(BrainResult(state, run_id='c9-run'), approve=lambda _t, _a: True, max_steps=4)
    assert result.status == 'completed'
    assert any(e.get('kind') == 'company_redelegated' and e.get('to_tool') == 'company_backup' for e in result.state.trace)
    assert any(item.get('step_id') == 's1' and item.get('ok') for item in result.state.observations)
    assert result.state.company_coordination.get('active_redelegations')

from __future__ import annotations

from pathlib import Path


def test_kernel_observed_answer_fallback_constructs_default_decision():
    from app.brain.kernel import CognitiveKernel
    from app.brain.models import CognitiveState

    kernel = object.__new__(CognitiveKernel)
    state = CognitiveState('fallback', session_id='name-binding-kernel')
    response = kernel._compose_observed_answer(state, {})
    assert response == "I won't guess without evidence."


def test_company_recovery_redelegation_builds_routing_candidates(monkeypatch, tmp_path: Path):
    from app.brain.models import PlannedAction
    from app.learning.store import LearningStore
    from app.organization import DEFAULT_COMPANY
    from app.organization import routing as routing_module
    from app.organization.recovery import CompanyRecoveryManager
    from app.runtime.registry import Tool

    calls: list[int] = []

    class FakeController:
        def __init__(self, organization, learning_store):
            self.organization = organization
            self.learning_store = learning_store

        def rank(self, candidates):
            candidates = tuple(candidates)
            calls.append(len(candidates))
            return tuple(type('Ranked', (), {'candidate': candidate, 'routing_score': 0.5}) for candidate in candidates)

    monkeypatch.setattr(routing_module, 'AdaptiveDelegationController', FakeController)

    def fail():
        raise RuntimeError('primary failed')

    tools = {
        'primary_data': Tool(
            name='primary_data', description='primary', params={}, fn=fail,
            capability='recovery-analysis', organization_department='data', organization_role='data:data-analyst',
            verification_level='strong', cost=1.0,
        ),
        'backup_data': Tool(
            name='backup_data', description='backup', params={}, fn=lambda: {'ok': True},
            capability='recovery-analysis', organization_department='data', organization_role='data:data-analyst',
            verification_level='strong', cost=1.2,
        ),
    }
    store = LearningStore(tmp_path / 'learning.db')
    store.record_company_delegation_outcome(
        capability='recovery-analysis', department='data', specialist='data:data-analyst',
        tool='backup_data', verified=True, duration=0.1, run_id='binding-seed',
    )

    action = PlannedAction('s1', 'recovery-analysis', 'primary_data', {})
    decision = CompanyRecoveryManager().decide(
        action=action,
        error='primary failed',
        organization=DEFAULT_COMPANY.registry,
        tool_registry=tools,
        learning_store=store,
    )

    assert decision.decision == 'redelegate'
    assert decision.selected is not None
    assert decision.selected.tool == 'backup_data'
    assert calls == [1]


def test_learning_store_replay_priority_update_resolves_helper_from_module_scope(tmp_path: Path):
    from app.learning.models import ExperienceRecord
    from app.learning.store import LearningStore

    store = LearningStore(tmp_path / 'learning.db')
    transition = {
        'transition_id': 'binding-transition',
        'state_before': 'state-a',
        'action': {'tool': 'calculator', 'args': {'expression': '2+2'}},
        'state_after': 'state-b',
        'outcome': {'ok': True},
        'verified': True,
    }
    record = ExperienceRecord(
        run_id='binding-run', goal='calculate', task_signature='calculate', status='completed',
        reward=1.0, verified_rate=1.0, steps=({'tool': 'calculator', 'status': 'done'},),
        failure_class=None, lesson_keys=(), session_id='binding-session', created_at='2026-10-06T00:00:00Z',
        transitions=(transition,), operation='calculate',
    )

    assert store.index_replay_transitions(record) == 1
    item = store.replay_items(limit=1)[0]
    changed = store.update_replay_priorities([
        {'transition_id': item.transition_id, 'transition': transition, 'occurrence_count': 0, 'contradictory': False}
    ])
    assert changed == 1

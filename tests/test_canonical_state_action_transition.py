from __future__ import annotations

from app.brain import ActionSpec, CanonicalState, Transition
from app.brain.models import CandidateAction


def test_canonical_state_fingerprint_is_order_invariant_and_text_independent():
    first = CanonicalState(
        facts=(('b', 2), ('a', 1)),
        variables=(('mode', 'active'),),
        capabilities=('write', 'read'),
        resources=(('budget', 10.0),),
        active_goals=('ship change',),
        constraints=('safe',),
        pending_actions=('s1', 's2'),
        uncertainty=('unknown-location',),
    )
    second = CanonicalState(
        facts=(('a', 1), ('b', 2)),
        variables=(('mode', 'active'),),
        capabilities=('read', 'write'),
        resources=(('budget', 10),),
        active_goals=('ship change',),
        constraints=('safe',),
        pending_actions=('s1', 's2'),
        uncertainty=('unknown-location',),
    )
    assert first.fingerprint() == second.fingerprint()
    assert 'user_text' not in first.to_dict()
    assert 'session_id' not in first.to_dict()


def test_action_spec_signature_ignores_parameter_order_and_action_instance_id():
    candidate = CandidateAction(
        capability='calculation', tool='calculator', score=0.5, reason='semantic-fit',
        preconditions=('ready',), effects=('calculation_completed',), cost=1.0,
    )
    a = ActionSpec.from_candidate(candidate, action_id='s1', parameters={'expression': '2+2', 'precision': 2})
    b = ActionSpec.from_candidate(candidate, action_id='s9', parameters={'precision': 2, 'expression': '2+2'})
    assert a.signature() == b.signature()
    assert a.to_dict()['historical_success'] == 0
    assert a.to_dict()['historical_failure'] == 0
    assert a.to_dict()['expected_reward'] is None


def test_transition_separates_prediction_from_actual_state():
    before = CanonicalState(facts=(('status', 'draft'),))
    predicted = CanonicalState(facts=(('status', 'ready'),))
    after = CanonicalState(facts=(('status', 'failed'),))
    action = ActionSpec('s1', 'build', 'build_project', expected_effects=('ready',))
    transition = Transition.from_states(
        before, action, after, predicted=predicted, outcome={'ok': False},
        reward=-0.5, prediction_error=1.0, verified=True, metadata={'source': 'test'},
    )
    data = transition.to_dict()
    assert data['state_before'] == before.fingerprint()
    assert data['predicted_state'] == predicted.fingerprint()
    assert data['state_after'] == after.fingerprint()
    assert data['prediction_error'] == 1.0
    assert data['verified'] is True
    assert transition.fingerprint()


def test_cognitive_state_projects_existing_brain_objects_into_canonical_state():
    from app.brain.models import CognitiveState, GoalSpec, PlannedAction

    state = CognitiveState(user_text='احسب 2+2', session_id='private-session')
    state.goal = GoalSpec('calculation', 'احسب 2+2', desired_state=('calculation_completed',), constraints=('safe',))
    state.plan = [PlannedAction('s1', 'calculation', 'calculator', expected_effects=('calculation_completed',))]
    state.world_facts = {'ready': True}
    state.uncertainties = ['low_evidence']
    canonical = state.to_canonical_state()

    assert canonical.facts == (('ready', True),)
    assert canonical.active_goals == ('احسب 2+2',)
    assert canonical.constraints == ('safe',)
    assert canonical.pending_actions == ('s1',)
    assert 'private-session' not in canonical.to_dict().__repr__()
    assert 'احسب 2+2' in canonical.to_dict()['active_goals']

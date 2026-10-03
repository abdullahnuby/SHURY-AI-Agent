from pathlib import Path

from app.brain import CognitiveKernel
from app.brain.learning import BrainExperienceStore
from app.brain.planner import make_goal, plan, replan
from app.brain.self_model import SelfModel
from app.brain.store import BrainStateStore
from app.brain.perception import perceive
from app.knowledge.memory import Memory
from app.runtime.registry import Tool


def test_method_planner_and_state_filter_keep_unsatisfied_suffix(tmp_path: Path):
    frame = perceive('احسب 25 * 16 واحفظ النتيجة باسم total')
    goal = make_goal(frame)
    from app.brain.capabilities import discover_candidates
    registry = {
        'calculator': Tool('calculator', '', {'expression': 'x'}, lambda expression: 400,
                           capability='calculate', produces=('calculation_completed',)),
        'remember_fact': Tool('remember_fact', '', {'key': 'k', 'value': 'v'}, lambda key, value: True,
                              capability='remember_fact', produces=('fact_saved',)),
    }
    candidates = discover_candidates(frame, registry)
    state = type('S', (), {'world_facts': {'calculation_completed': 400}})()
    steps = replan(goal, frame, candidates, state=state, failed_tool='remember_fact')
    assert [s.tool for s in steps] == ['calculator'] or steps == []
    # If the only persistence method is excluded, the planner must not fabricate a save step.


def test_runtime_failure_triggers_observation_conditioned_replan(tmp_path: Path):
    calls = []

    def failing(query):
        calls.append('answer_question')
        raise RuntimeError('primary source unavailable')

    def fallback(query):
        calls.append('agentic_rag')
        return {'answer': 'grounded answer', 'evidence': [{'title': 'source'}]}

    registry = {
        'answer_question': Tool('answer_question', '', {'query': 'q'}, failing,
                                capability='question_answering', produces=('answer_grounded',), cost=1.0,
                                verification_level='strong'),
        'agentic_rag': Tool('agentic_rag', '', {'query': 'q'}, fallback,
                            capability='agentic_rag', produces=('verified_evidence', 'grounded_answer'), cost=2.0,
                            verification_level='strong'),
    }
    brain = CognitiveKernel(
        memory=Memory(tmp_path / 'memory.db'), registry=registry,
        state_store=BrainStateStore(tmp_path / 'state.db'),
        experience_store=BrainExperienceStore(tmp_path / 'exp.db'),
    )
    result = brain.act('ما هو الثقب الأسود؟', session_id='replan-1')
    assert result.status == 'completed'
    assert calls == ['answer_question', 'agentic_rag']
    assert result.runtime_state['replans'] == 1
    assert any(x.get('kind') == 'replan' for x in result.state.trace)
    assert 'grounded answer' in result.response


def test_verified_experience_changes_future_method_grounding(tmp_path: Path):
    mem = Memory(tmp_path / 'memory.db')
    exp = BrainExperienceStore(tmp_path / 'exp.db')
    # Make the more expensive agentic method the empirically preferred route.
    for _ in range(3):
        exp.record(session_id='s', user_text='q', operation='query_knowledge', capability='agentic_rag',
                   tool='agentic_rag', status='completed', verified=True, reward=1.0)
    brain = CognitiveKernel(memory=mem, experience_store=exp)
    result = brain.think('ما هو الثقب الأسود؟', session_id='s2')
    assert result.state.plan
    assert result.state.plan[0].tool == 'agentic_rag'
    assert result.state.plan[0].rationale


def test_self_model_surfaces_observed_limits(tmp_path: Path):
    exp = BrainExperienceStore(tmp_path / 'exp.db')
    for _ in range(3):
        exp.record(session_id='s', user_text='q', operation='research', capability='internet_research',
                   tool='web_research', status='failed', verified=False, reward=0.0, lesson='network failure')
    registry = {'web_research': Tool('web_research', '', {'query': 'q'}, lambda query: '', capability='internet_research')}
    snap = SelfModel(registry, exp).snapshot()
    assert snap['limits']
    assert snap['limits'][0]['tool'] == 'web_research'


def test_belief_revision_preserves_history_event(tmp_path: Path):
    brain = CognitiveKernel(memory=Memory(tmp_path / 'memory.db'), state_store=BrainStateStore(tmp_path / 'state.db'),
                            experience_store=BrainExperienceStore(tmp_path / 'exp.db'))
    brain._remember_belief('s1', 'favorite_color', 'أزرق')
    brain._remember_belief('s1', 'favorite_color', 'أخضر')
    beliefs = brain._load_beliefs('s1')
    assert beliefs[0].value == 'أخضر'
    assert beliefs[0].revision == 2
    events = brain.state_store.recent_events('s1', limit=20)
    assert any(e['kind'] == 'belief_revision' and e['payload']['previous_value'] == 'أزرق' for e in events)


def test_procedure_family_is_induced_from_verified_multi_step_experience(tmp_path: Path):
    exp = BrainExperienceStore(tmp_path / 'exp.db')
    exp.record(session_id='s', user_text='q', operation='compound_calculate_remember', capability='calculate',
               tool='remember_fact', status='completed', verified=True, reward=1.0,
               plan_signature='[{"tool":"calculator"},{"tool":"remember_fact"}]', lesson='verified procedure')
    procedures = exp.procedure_candidates('compound_calculate_remember')
    assert procedures
    assert procedures[0]['workflow'] == ['calculator', 'remember_fact']
    assert procedures[0]['successes'] == 1

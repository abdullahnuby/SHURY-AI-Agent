from pathlib import Path


def test_chat_layout_is_bounded_to_viewport():
    css = Path('app/interfaces/web/static/styles.css').read_text(encoding='utf-8')
    assert 'body { height:100dvh; overflow:hidden; }' in css
    assert '.chat-panel { min-width:0; min-height:0; height:100dvh;' in css
    assert '.messages { flex:1 1 auto; min-height:0; overflow-y:auto;' in css


def test_old_task_envelope_is_never_rendered_as_assistant_text():
    js = Path('app/interfaces/web/static/app.js').read_text(encoding='utf-8')
    assert 'function humanizeAgentText(value)' in js
    assert 'const assistantText = humanizeAgentText(episode.assistant_text);' in js


def test_natural_memory_question_retrieves_note():
    from pathlib import Path
    from app.api import run_agent
    from app.knowledge.memory import configure

    db = Path('/tmp/shury-chat-ui-regression.db')
    if db.exists():
        db.unlink()
    memory = configure(db)
    memory.add_note('عندي اجتماع الساعة 10')

    state = run_agent('متى الاجتماع؟', session_id='chat-ui-regression')

    assert state.status == 'completed'
    assert 'اجتماع' in state.final_message
    assert '10' in state.final_message
    assert state.plan.steps[0].tool == 'search_memory'
    assert state.plan.steps[0].args['query'] == 'اجتماع'


def test_persisted_envelope_is_humanized():
    from app.interfaces.web.server import humanize_persisted_assistant_text

    raw = '{"task_id":"abc","state":{"final_message":"تم التنفيذ بنجاح."},"status":"completed"}'
    assert humanize_persisted_assistant_text(raw) == 'تم التنفيذ بنجاح.'


def test_web_server_does_not_eagerly_load_semantic_model():
    import os
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    code = "import sys; import app.interfaces.web.server; assert 'sentence_transformers' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def test_serialized_brain_exposes_compact_decision_evidence(tmp_path: Path):
    from app.api import run_brain
    from app.brain.kernel import CognitiveKernel
    from app.brain.store import BrainStateStore
    from app.knowledge.memory import Memory
    from app.learning.store import LearningStore
    from app.runtime.registry import Tool

    registry = {
        'research_memory_search': Tool(
            'research_memory_search', 'local research evidence', {'query': 'str'},
            lambda query: {'evidence': [{'title': 'local evidence', 'snippet': query}]},
            capability='research_memory_retrieval', produces=('historical_research_evidence',),
            cost=0.6, duration=0.05, risk='low', idempotent=True,
            verification_level='strong', exploration_safe=True, emits_world_delta=False,
            information_domains=('research', 'learning', 'memory'), information_gain_prior=0.92,
            build_args=lambda goal: {'query': str(goal)},
        ),
        'research_and_learn': Tool(
            'research_and_learn', 'learn locally in test', {'query': 'str'},
            lambda query: {
                'query': query, 'evidence_count': 1, 'new_evidence_count': 1,
                'route': [{'source': 'test'}],
                'evidence': [{'title': 'learned evidence', 'url': 'https://example.test', 'snippet': query}],
            },
            capability='open_world_learning', produces=('research_evidence', 'learning_candidate'),
            cost=1.0, duration=0.05, risk='low', idempotent=True,
            verification_level='strong', exploration_safe=True, emits_world_delta=False,
            information_domains=('research', 'learning'), information_gain_prior=0.95,
            match=lambda _goal: False,
            build_args=lambda goal: {'query': str(goal)},
        ),
    }
    result = run_brain(
        'learn how to improve',
        session_id='ui-cognition',
        kernel=CognitiveKernel(
            memory=Memory(tmp_path / 'memory.db'),
            registry=registry,
            state_store=BrainStateStore(tmp_path / 'brain_state.db'),
            experience_store=LearningStore(tmp_path / 'learning.db'),
        ),
    )
    from app.interfaces.web.server import serialize_state
    payload = serialize_state(result)
    summary = payload['cognitive']['summary']
    assert summary['decision'] == 'research'
    assert summary['plan']
    assert summary['alternatives']
    if summary['exploration'] is not None:
        assert summary['exploration']['information_gain'] >= 0.0
    assert summary['planning_mode'] in {'deterministic', 'model-based', 'exploration'}

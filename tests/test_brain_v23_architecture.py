from pathlib import Path

from app.brain import CognitiveKernel
from app.brain.learning import BrainExperienceStore
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory


def make_kernel(tmp_path: Path) -> CognitiveKernel:
    return CognitiveKernel(
        memory=Memory(tmp_path / 'memory.db'),
        state_store=BrainStateStore(tmp_path / 'brain_state.db'),
        experience_store=BrainExperienceStore(tmp_path / 'brain_experience.db'),
    )


def test_belief_persists_across_kernel_instances(tmp_path):
    first = make_kernel(tmp_path)
    first._remember_belief('s1', 'name', 'عبدالله')
    second = make_kernel(tmp_path)
    result = second.think('أنا مين؟', session_id='s1')
    assert result.state.decision is not None
    assert result.state.decision.kind == 'respond'
    assert 'عبدالله' in result.response


def test_question_uses_local_legacy_evidence_before_external_research(tmp_path):
    mem = Memory(tmp_path / 'memory.db')
    mem.set_fact('meeting', 'الساعة 10')
    brain = CognitiveKernel(
        memory=mem,
        state_store=BrainStateStore(tmp_path / 'brain_state.db'),
        experience_store=BrainExperienceStore(tmp_path / 'brain_experience.db'),
    )
    result = brain.think('متى الاجتماع؟', session_id='s1')
    assert result.state.decision.kind == 'respond'
    assert '10' in result.response
    assert result.state.memories


def test_compound_goal_has_dependency_dataflow(tmp_path):
    brain = make_kernel(tmp_path)
    result = brain.think('احسب 25 * 16 واحفظ النتيجة باسم total', session_id='s1')
    assert result.state.decision.kind == 'execute'
    assert [x.tool for x in result.state.plan] == ['calculator', 'remember_result']
    assert result.state.plan[1].depends_on == ('s1',)
    assert result.state.plan[1].args['value'] == '{{s1}}'


def test_unknown_request_reports_capability_gap(tmp_path):
    brain = make_kernel(tmp_path)
    result = brain.think('نفذ المهمة الغامضة دي', session_id='s1')
    assert result.state.decision.kind == 'clarify'
    assert 'goal_or_capability' in result.state.decision.missing_information or 'capability_not_identified' in result.state.decision.missing_information


def test_no_external_ml_import_in_v23_core():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / 'app' / 'brain'
    for path in root.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        assert 'sentence_transformers' not in text

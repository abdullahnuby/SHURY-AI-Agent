from __future__ import annotations
import tempfile
from pathlib import Path

from app.brain import CognitiveKernel
from app.brain.learning import BrainExperienceStore
from app.knowledge.memory import Memory


def kernel(tmp_path: Path) -> CognitiveKernel:
    mem = Memory(tmp_path / 'memory.db')
    mem.set_fact('name', 'عبدالله')
    return CognitiveKernel(memory=mem, experience_store=BrainExperienceStore(tmp_path / 'brain.db'))


def test_identity_is_answered_from_memory(tmp_path):
    result = kernel(tmp_path).think('انا مين؟', session_id='s1')
    assert result.state.decision.kind == 'respond'
    assert result.state.decision.answer_source == 'memory'
    assert 'عبدالله' in result.response


def test_memory_question_is_semantically_reduced(tmp_path):
    mem = Memory(tmp_path / 'memory.db')
    mem.set_fact('meeting', 'الساعة 10')
    brain = CognitiveKernel(memory=mem, experience_store=BrainExperienceStore(tmp_path / 'brain.db'))
    result = brain.think('متى الاجتماع؟', session_id='s1')
    assert result.state.decision.kind == 'respond'
    assert '10' in result.response
    assert any(e.to_dict()['kind'] == 'memory' for e in result.state.memories)


def test_greeting_does_not_research(tmp_path):
    result = kernel(tmp_path).think('ايه الأخبار؟', session_id='s1')
    assert result.state.decision.kind == 'respond'
    assert result.state.decision.answer_source == 'conversation'


def test_generic_question_requests_evidence(tmp_path):
    result = kernel(tmp_path).think('ما هو الثقب الأسود؟', session_id='s1')
    assert result.state.decision.kind == 'research'
    assert result.state.decision.answer_source in {'rag_or_web', 'web'}


def test_calculation_is_actionable(tmp_path):
    result = kernel(tmp_path).think('احسب 25 * 16', session_id='s1')
    assert result.state.decision.kind == 'execute'
    assert result.state.decision.tool == 'calculator'


def test_brain_never_returns_internal_json_as_response(tmp_path):
    result = kernel(tmp_path).think('انا مين؟', session_id='s1')
    assert not result.response.lstrip().startswith('{')
    assert 'task_id' not in result.response

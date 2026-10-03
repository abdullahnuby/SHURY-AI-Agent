from pathlib import Path

from app.brain import CognitiveKernel
from app.brain.perception import perceive
from app.brain.learning import BrainExperienceStore
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory


def kernel(tmp_path: Path) -> CognitiveKernel:
    return CognitiveKernel(memory=Memory(tmp_path / 'memory.db'),
                           state_store=BrainStateStore(tmp_path / 'state.db'),
                           experience_store=BrainExperienceStore(tmp_path / 'exp.db'))


def test_identity_paraphrases_share_semantic_operation():
    phrases = ['أنا مين؟', 'مين أنا؟', 'What is my name?', 'فاكر اسمي؟']
    assert {perceive(x).requested_operation for x in phrases} == {'query_identity'}


def test_capability_paraphrases_are_not_knowledge_questions():
    phrases = ['ما الذي تستطيع فعله؟', 'ماذا تستطيع؟', 'What can you do?', 'What can you help with?']
    assert {perceive(x).requested_operation for x in phrases} == {'query_capabilities'}


def test_deictic_skill_request_uses_previous_goal(tmp_path: Path):
    brain = kernel(tmp_path)
    brain.think('راجع المشروع وشغل الاختبارات', session_id='s1')
    frame = brain.perceive('اكتشف المهارات المناسبة للمهمة دي', session_id='s1').semantic
    assert frame.requested_operation == 'skill_query'
    assert frame.slot('reference_target') == 'راجع المشروع وشغل الاختبارات'
    assert frame.slot('query') == 'راجع المشروع وشغل الاختبارات'


def test_deictic_reference_without_context_is_not_executed(tmp_path: Path):
    result = kernel(tmp_path).think('اكتشف المهارات المناسبة للمهمة دي', session_id='empty')
    assert result.state.decision.kind == 'clarify'
    assert 'anaphoric_reference_unresolved' in result.state.decision.missing_information

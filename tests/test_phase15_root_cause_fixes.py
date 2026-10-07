from __future__ import annotations

from pathlib import Path

from app.api import run_brain
from app.brain import CognitiveKernel
from app.brain.store import BrainStateStore
from app.intelligence.semantic import semantic_understand
from app.knowledge.memory import Memory
from app.learning.store import LearningStore
from app.runtime.registry import Tool


def _kernel(tmp_path: Path, *, registry=None) -> CognitiveKernel:
    return CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        registry=registry,
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=LearningStore(tmp_path / "learning.db"),
    )


def test_identity_recall_has_canonical_memory_contract(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.set_fact("name", "عبدالله")
    result = _kernel(tmp_path, registry=None)
    result.memory.set_fact("name", "عبدالله")
    state = result.think("انا مين؟", session_id="identity")
    assert state.state.semantic.requested_operation == "query_identity"
    assert state.state.semantic.slot("key") == "name"
    assert state.state.decision.answer_source == "memory"
    assert any(item.kind == "memory" for item in state.state.memories)


def test_normalized_egyptian_social_question_stays_conversational():
    parse = semantic_understand("ايه الأخبار؟")
    assert parse.top_intent is not None
    assert parse.top_intent.name == "how_are_you"
    assert parse.speech_act == "greeting"


def test_arabic_copular_question_is_not_anaphoric():
    parse = semantic_understand("ما هو الثقب الأسود؟")
    assert not any(reason == "anaphoric_reference_unresolved" for reason in parse.ambiguity_reasons)
    assert not any(ref.text == "هو" and not ref.resolved for ref in parse.references)


def test_external_learning_preserves_learning_capability_and_research_route(tmp_path: Path):
    brain = _kernel(tmp_path)
    result = brain.think("learn from web how to be smarter", session_id="research-learning")
    assert result.state.semantic is not None
    assert result.state.semantic.requested_operation == "research"
    assert result.state.semantic.slot("query") == "how to be smarter"
    assert result.state.plan
    assert result.state.plan[0].tool in {"research_and_learn", "web_research", "internet_research"}


def test_open_ended_learning_maps_to_learning_intent_with_topic(tmp_path: Path):
    brain = _kernel(tmp_path)
    result = brain.think("learn how to improve", session_id="open-learning")
    assert result.state.semantic is not None
    assert result.state.semantic.requested_operation == "learning_intent"
    assert result.state.semantic.slot("learning_topic") == "how to improve"
    assert result.state.decision.kind == "research"


def test_calculation_expression_reaches_brain_planner(tmp_path: Path):
    brain = _kernel(tmp_path)
    result = brain.think("احسب 25 * 16", session_id="calculation")
    assert result.state.semantic is not None
    assert result.state.semantic.slot("expression") == "25 * 16"
    assert result.state.plan
    assert result.state.plan[0].tool == "calculator"
    assert result.state.decision.kind == "execute"


def test_successful_execution_records_learning_transition(tmp_path: Path):
    registry = {
        "calculator": Tool(
            "calculator", "deterministic calculator", {"expression": "str"},
            lambda expression: 4,
            capability="calculate", produces=("calculation_completed",),
            verification_level="strong",
        )
    }
    brain = _kernel(tmp_path, registry=registry)
    result = brain.act("احسب 2 + 2", session_id="learning")
    assert result.status == "completed"
    events = [event for event in result.state.trace if event.get("kind") == "learning_recorded"]
    assert events and events[-1]["transition_count"] == 1
    assert brain.learning.store.get_experience(result.run_id) is not None


def test_brain_clarification_status_is_needs_user(tmp_path):
    brain = _kernel(tmp_path)
    result = brain.think("update it", session_id="clarify-status")
    executed = brain._execute_result(result, approve=lambda *_: True)
    assert executed.status == "needs_user"
    assert executed.state.decision is not None
    assert executed.state.decision.kind == "clarify"

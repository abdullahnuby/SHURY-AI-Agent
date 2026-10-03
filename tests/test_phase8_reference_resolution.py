from __future__ import annotations

from pathlib import Path

from app.brain import CognitiveKernel
from app.brain.store import BrainStateStore
from app.intelligence.semantic.parser import semantic_understand
from app.intelligence.semantic.references import resolve_references
from app.knowledge.memory import Memory
from app.learning.store import LearningStore


def _kernel(tmp_path: Path) -> CognitiveKernel:
    return CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=LearningStore(tmp_path / "learning.db"),
    )


def test_arabic_conjoined_candidates_keep_attached_pronoun_ambiguous() -> None:
    refs = resolve_references("راجع المشروع والمستودع وعدله", {}, [])
    attached = [ref for ref in refs if ref.text == "ه"]
    assert attached
    assert attached[0].resolved is False
    assert attached[0].basis == "multiple same-utterance antecedents"


def test_arabic_task_deictic_resolves_to_previous_whole_goal() -> None:
    parsed = semantic_understand(
        "اكتشف المهارات المناسبة للمهمة دي",
        world={"last_goal": "review the project and run tests", "last_outputs": {}},
    )
    assert parsed.references
    resolved = [ref for ref in parsed.references if ref.text == "دي" and ref.resolved]
    assert resolved
    assert resolved[0].target == "review the project and run tests"
    assert parsed.slots.get("reference_target") == "review the project and run tests"


def test_previous_turn_candidates_are_ambiguous_when_two_objects_are_present() -> None:
    refs = resolve_references(
        "update it",
        {"last_goal": "راجع التقرير والملف", "last_outputs": {}},
        [],
    )
    pronoun = next(ref for ref in refs if ref.text == "it")
    assert pronoun.resolved is False
    assert pronoun.basis == "multiple contextual antecedents"


def test_information_question_is_not_used_as_generic_previous_goal() -> None:
    refs = resolve_references(
        "update it",
        {"last_goal": "what is the time?", "last_outputs": {}},
        [],
    )
    pronoun = next(ref for ref in refs if ref.text == "it")
    assert pronoun.resolved is False


def test_gendered_pronouns_require_compatible_person_antecedent() -> None:
    male = resolve_references("my brother is Ahmed and he is available", {}, [])
    he = next(ref for ref in male if ref.text == "he")
    assert he.resolved is True
    assert he.target == "Ahmed"

    female = resolve_references("my sister is Sara and she is available", {}, [])
    she = next(ref for ref in female if ref.text == "she")
    assert she.resolved is True
    assert she.target == "Sara"

    incompatible = resolve_references("my brother is Ahmed and she is available", {}, [])
    she = next(ref for ref in incompatible if ref.text == "she")
    assert she.resolved is False


def test_canonical_brain_preserves_reference_ambiguity(tmp_path: Path) -> None:
    brain = _kernel(tmp_path)
    result = brain.think("راجع المشروع والمستودع وعدله", session_id="phase8-ambiguity")
    decision = result.state.decision
    assert decision is not None
    assert decision.kind == "clarify"
    assert "anaphoric_reference_unresolved" in decision.missing_information
    assert result.state.semantic is not None
    assert result.state.semantic.slot("reference_target") == ""


def test_canonical_brain_stops_ambiguous_frame_before_retrieval_or_planning(tmp_path: Path, monkeypatch) -> None:
    brain = _kernel(tmp_path)

    def unexpected_stage(*args, **kwargs):
        raise AssertionError("ambiguous request entered retrieval or planning")

    monkeypatch.setattr(brain, "retrieve", unexpected_stage)
    monkeypatch.setattr(brain, "_plan_state", unexpected_stage)
    result = brain.think("راجع المشروع والمستودع وعدله", session_id="phase8-early-ambiguity")

    assert result.state.decision is not None
    assert result.state.decision.kind == "clarify"
    assert result.state.semantic is not None
    assert "anaphoric_reference_unresolved" in result.state.semantic.uncertainty
    assert not any(event.get("kind") in {"retrieval", "planning", "exploration_decision"} for event in result.state.trace)


def test_canonical_brain_executes_valid_calculation_after_ambiguity_gate(tmp_path: Path) -> None:
    brain = _kernel(tmp_path)
    result = brain.act("calculate 2+2", session_id="phase8-valid-calculation", approve=lambda *_: True)

    assert result.status == "completed"
    assert result.runtime_state["outputs"]
    assert 4 in result.runtime_state["outputs"].values()
    assert any(
        event.get("kind") == "action_observed" and event.get("tool") == "calculator" and event.get("ok")
        for event in result.state.trace
    )


def test_canonical_brain_tracks_latest_goal_for_reference_context(tmp_path: Path) -> None:
    brain = _kernel(tmp_path)
    sid = "phase8-topic-order"
    brain.think("review the project", session_id=sid)
    brain.think("inspect the repository", session_id=sid)
    result = brain.think("check it", session_id=sid)
    assert result.state.semantic is not None
    assert result.state.semantic.slot("reference_target") == "repository"



def test_canonical_brain_language_switch_preserves_whole_task_reference(tmp_path: Path) -> None:
    brain = _kernel(tmp_path)
    sid = "phase8-language-switch"
    goal = "review the project and run tests"
    brain.think(goal, session_id=sid)
    result = brain.think("اكتشف المهارات المناسبة للمهمة دي", session_id=sid)
    assert result.state.semantic is not None
    assert result.state.semantic.slot("reference_target") == goal
    assert result.state.semantic.slot("query") == goal

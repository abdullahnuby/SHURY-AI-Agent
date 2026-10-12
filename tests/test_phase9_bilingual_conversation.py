from __future__ import annotations

from pathlib import Path
import random

from app.api import run_brain
from app.brain import CognitiveKernel
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory
from app.learning.store import LearningStore


def _kernel(tmp_path: Path) -> CognitiveKernel:
    return CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=LearningStore(tmp_path / "learning.db"),
    )


def _approve(*_args):
    return True


def test_arabic_to_english_memory_continuity(tmp_path: Path):
    brain = _kernel(tmp_path)
    sid = "phase9-ar-en-memory"
    first = brain.act("أنا اسمي عبدالله", session_id=sid, approve=_approve)
    second = brain.act("What is my name?", session_id=sid, approve=_approve)
    assert first.status == "completed"
    assert second.status == "completed"
    assert second.state.semantic is not None
    assert second.state.semantic.language == "en"
    assert second.state.semantic.requested_operation == "query_identity"
    assert "عبدالله" in second.response


def test_english_to_arabic_memory_continuity(tmp_path: Path):
    brain = _kernel(tmp_path)
    sid = "phase9-en-ar-memory"
    first = brain.act("My city is Luxor", session_id=sid, approve=_approve)
    second = brain.act("أين مدينتي؟", session_id=sid, approve=_approve)
    assert first.status == "completed"
    assert second.status == "completed"
    assert second.state.semantic is not None
    assert second.state.semantic.language == "ar"
    assert second.state.semantic.slot("key") == "city"
    assert second.state.semantic.requested_operation == "query_memory"
    assert "luxor" in second.response.casefold()


def test_arabic_to_english_reference_preserves_previous_tool_route(tmp_path: Path):
    brain = _kernel(tmp_path)
    sid = "phase9-ar-en-reference"
    first = brain.act("راجع المشروع", session_id=sid, approve=_approve)
    second = brain.act("Check it", session_id=sid, approve=_approve)
    assert first.status == "completed"
    assert second.status == "completed"
    assert second.state.semantic is not None
    assert second.state.semantic.language == "en"
    assert second.state.semantic.requested_operation == "development_inspection"
    assert second.state.semantic.slot("reference_target") in {"project", "المشروع"}
    assert any(step.tool == "inspect_project" for step in second.state.plan)


def test_english_to_arabic_task_deictic_preserves_previous_task(tmp_path: Path):
    brain = _kernel(tmp_path)
    sid = "phase9-en-ar-reference"
    first = brain.act("review the project", session_id=sid, approve=_approve)
    second = brain.act("راجع المهمة دي", session_id=sid, approve=_approve)
    assert first.status == "completed"
    assert second.status == "completed"
    assert second.state.semantic is not None
    assert second.state.semantic.language == "ar"
    assert second.state.semantic.requested_operation == "development_inspection"
    assert second.state.semantic.slot("reference_target") == "review the project"
    assert any(step.tool == "inspect_project" for step in second.state.plan)


def test_egyptian_to_english_memory_profile_stays_on_memory(tmp_path: Path):
    brain = _kernel(tmp_path)
    sid = "phase9-egy-en-profile"
    brain.act("اسمي عبدالله", session_id=sid, approve=_approve)
    first = brain.act("فاكر اسمي؟", session_id=sid, approve=_approve)
    second = brain.act("What do you remember about me?", session_id=sid, approve=_approve)
    assert first.status == "completed"
    assert second.status == "completed"
    assert second.state.semantic is not None
    assert second.state.semantic.language == "en"
    assert second.state.semantic.requested_operation == "query_memory"
    assert not any(step.tool == "research_memory_search" for step in second.state.plan)


def test_mixed_technical_language_routes_to_same_development_capability(tmp_path: Path):
    brain = _kernel(tmp_path)
    sid = "phase9-mixed-technical"
    first = brain.act("أنا عاوزك تعمل code review للـ project", session_id=sid, approve=_approve)
    second = brain.act("Now inspect it", session_id=sid, approve=_approve)
    assert first.status == "completed"
    assert second.status == "completed"
    assert first.state.semantic is not None and first.state.semantic.language == "mixed"
    assert second.state.semantic is not None and second.state.semantic.language == "en"
    assert first.state.semantic.requested_operation == "development_inspection"
    assert second.state.semantic.requested_operation == "development_inspection"
    assert second.state.semantic.slot("reference_target") == "project"


def test_english_city_question_variants_use_canonical_memory_route(tmp_path: Path):
    brain = _kernel(tmp_path)
    sid = "phase9-city-question-variants"
    brain.act("My city is Luxor", session_id=sid, approve=_approve)
    for text in ("Where is my city?", "What city am I in?", "What city do I live in?"):
        result = brain.act(text, session_id=sid, approve=_approve)
        assert result.status == "completed"
        assert result.state.semantic is not None
        assert result.state.semantic.requested_operation == "query_memory"
        assert result.state.semantic.slot("key") == "city"
        assert "luxor" in result.response.casefold()


def test_bilingual_name_recall_followups_keep_memory_identity_route(tmp_path: Path):
    brain = _kernel(tmp_path)
    sid = "phase9-name-followup"
    brain.act("أنا اسمي عبدالله", session_id=sid, approve=_approve)
    for text in ("Tell me my name again.", "قولّي اسمي؟"):
        result = brain.act(text, session_id=sid, approve=_approve)
        assert result.status == "completed"
        assert result.state.semantic is not None
        assert result.state.semantic.requested_operation == "query_identity"
        assert result.state.semantic.slot("key") == "name"


def test_cross_language_followup_chain_does_not_switch_from_inspection_to_git(tmp_path: Path):
    brain = _kernel(tmp_path)
    sid = "phase9-inspection-chain"
    brain.act("راجع المشروع", session_id=sid, approve=_approve)
    brain.act("Check it", session_id=sid, approve=_approve)
    result = brain.act("Inspect it now", session_id=sid, approve=_approve)
    assert result.status == "completed"
    assert result.state.semantic is not None
    assert result.state.semantic.requested_operation == "development_inspection"
    assert any(step.tool == "inspect_project" for step in result.state.plan)


def test_msa_and_egyptian_arabic_memory_questions_share_the_same_contract(tmp_path: Path):
    brain = _kernel(tmp_path)
    sid = "phase9-arabic-variants"
    brain.act("مدينتي هي الأقصر", session_id=sid, approve=_approve)
    msa = brain.act("أين مدينتي؟", session_id=sid, approve=_approve)
    egy = brain.act("أنا من فين؟", session_id=sid, approve=_approve)
    assert msa.status == "completed" and egy.status == "completed"
    assert msa.state.semantic is not None and egy.state.semantic is not None
    assert msa.state.semantic.requested_operation == "query_memory"
    assert egy.state.semantic.requested_operation == "query_memory"
    assert msa.state.semantic.slot("key") == "city"
    assert egy.state.semantic.slot("key") == "origin"

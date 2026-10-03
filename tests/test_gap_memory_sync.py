from pathlib import Path

from app.brain import CognitiveKernel
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory
from app.intelligence.semantic import semantic_understand
from app.intelligence.semantic.slots import extract_slots
from app.learning.store import LearningStore


def _kernel(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    learning = LearningStore(tmp_path / "learning.db")
    state = BrainStateStore(tmp_path / "state.db")
    return CognitiveKernel(memory=mem, state_store=state, experience_store=learning), mem


def test_arabic_name_question_accepts_trailing_question_mark():
    slots = extract_slots("ما اسمي؟")
    assert slots.get("recall:key") == "name"
    slots = extract_slots("ما هو اسمي؟")
    assert slots.get("recall:key") == "name"


def test_identity_method_uses_requested_key_instead_of_fixed_name():
    p = semantic_understand("ما هي مدينتي")
    assert p.slots.get("recall:key") == "city"


def test_structured_recall_routes_non_name_keys_to_generic_memory():
    from app.brain.structured import validate_structured_goal
    goal, frame, _ = validate_structured_goal({"operation": "recall_fact", "goal": "what is my city?", "slots": {"recall:key": "city"}})
    assert goal.name == "query_memory"
    assert frame.requested_operation == "query_memory"


def test_canonical_brain_syncs_legacy_city_and_origin_memory(tmp_path: Path):
    brain, mem = _kernel(tmp_path)
    mem.set_fact("city", "Luxor")
    mem.set_fact("origin", "Luxor")

    city = brain.think("what is my city?", session_id="s1")
    assert city.state.semantic.requested_operation == "query_memory"
    assert city.state.plan and city.state.plan[0].tool == "recall_fact"
    executed_city = brain.act("what is my city?", session_id="s1", approve=lambda *_: True, max_steps=2)
    assert "Luxor" in executed_city.response
    assert any(b.predicate == "city" and b.value == "Luxor" for b in executed_city.state.beliefs)

    origin = brain.think("where am I from?", session_id="s1")
    assert origin.state.semantic.requested_operation == "query_memory"
    executed_origin = brain.act("where am I from?", session_id="s1", approve=lambda *_: True, max_steps=2)
    assert "Luxor" in executed_origin.response
    assert any(b.predicate == "origin" and b.value == "Luxor" for b in executed_origin.state.beliefs)

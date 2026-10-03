from pathlib import Path

from app.brain import CognitiveKernel
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory


def _kernel(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    state_store = BrainStateStore(tmp_path / "brain.db")
    return CognitiveKernel(memory=memory, state_store=state_store), memory, state_store


def _approve(*_args):
    return True


def test_canonical_memory_ignores_direct_brain_belief_divergence(tmp_path: Path):
    brain, memory, state_store = _kernel(tmp_path)
    first = brain.act("my city is Cairo", session_id="a", approve=_approve)
    assert first.status == "completed"
    assert memory.get_fact("city") == "cairo"

    state_store.upsert_belief(
        session_id="a", subject="user", predicate="city", value="Aswan",
        source="test", provenance="deliberate-divergence",
    )

    result = brain.act("what is my city?", session_id="a", approve=_approve)
    assert "cairo" in result.response.casefold()
    assert "aswan" not in result.response.casefold()
    assert memory.get_fact("city") == "cairo"


def test_correction_invalidates_stale_projection_across_sessions(tmp_path: Path):
    brain, memory, _state_store = _kernel(tmp_path)
    brain.act("my city is Luxor", session_id="a", approve=_approve)
    before = brain.act("what is my city?", session_id="b", approve=_approve)
    assert "luxor" in before.response.casefold()

    corrected = brain.act("my city is Cairo", session_id="a", approve=_approve)
    assert corrected.status == "completed"
    assert memory.get_fact("city") == "cairo"

    after = brain.act("what is my city?", session_id="b", approve=_approve)
    assert "cairo" in after.response.casefold()
    assert "luxor" not in after.response.casefold()


def test_forget_routes_through_brain_and_removes_canonical_memory(tmp_path: Path):
    brain, memory, state_store = _kernel(tmp_path)
    brain.act("my city is Cairo", session_id="a", approve=_approve)
    forgotten = brain.act("forget my city", session_id="a", approve=_approve)

    assert forgotten.status == "completed"
    assert memory.get_fact("city") is None
    assert all(b.predicate != "city" for b in forgotten.state.beliefs)

    # A stale derived belief must not resurrect deleted canonical memory.
    state_store.upsert_belief(
        session_id="b", subject="user", predicate="city", value="Luxor",
        source="test", provenance="stale-cache",
    )
    recalled = brain.act("what is my city?", session_id="b", approve=_approve)
    assert "luxor" not in recalled.response.casefold()
    assert memory.get_fact("city") is None


def test_arabic_forget_uses_the_same_canonical_memory_key(tmp_path: Path):
    brain, memory, _state_store = _kernel(tmp_path)
    brain.act("مدينتي هي الأقصر", session_id="a", approve=_approve)
    assert memory.get_fact("city") == "الاقصر"

    forgotten = brain.act("انس مدينتي", session_id="a", approve=_approve)
    assert forgotten.status == "completed"
    assert memory.get_fact("city") is None


def test_canonical_memory_persists_across_restart(tmp_path: Path):
    brain, memory, _state_store = _kernel(tmp_path)
    brain.act("my name is Abdullah", session_id="a", approve=_approve)
    assert memory.get_fact("name") == "abdullah"

    restarted, restarted_memory, _restarted_store = _kernel(tmp_path)
    result = restarted.act("what is my name?", session_id="a", approve=_approve)
    assert result.status == "completed"
    assert "abdullah" in result.response.casefold()
    assert restarted_memory.get_fact("name") == "abdullah"


def test_session_working_memory_is_isolated_while_durable_memory_is_explicitly_global(tmp_path: Path):
    _brain, memory, _state_store = _kernel(tmp_path)
    memory.working_put("session-a", "temporary checkout state", priority=5)
    assert memory.working_recall("session-a")
    assert memory.working_recall("session-b") == []

    memory.set_fact("project", "SHURY")
    assert memory.get_fact("project") == "SHURY"

    # Durable user memory is intentionally global; private turn/session context is not.
    assert memory.profile()
    assert memory.working_recall("session-b") == []

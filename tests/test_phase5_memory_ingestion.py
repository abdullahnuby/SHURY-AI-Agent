from pathlib import Path

from app.knowledge.memory import Memory
from app.knowledge.memory_ingestion import MemoryIngestionController
from app.knowledge.memory_models import MemoryCandidate


def test_ordinary_conversation_stays_episodic(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    result = memory.observe("hello, how are you?", owner_id="u1", session_id="s1", run_id="r1")
    assert result["episode_id"] > 0
    assert result["promoted"] == []
    assert result["candidates"] == []
    assert memory.profile(owner_id="u1") == []
    assert memory.recent_episodes("s1", owner_id="u1")


def test_explicit_high_confidence_fact_goes_through_full_pipeline(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    result = memory.observe("my name is John", owner_id="u1", session_id="s1", run_id="r1")
    assert len(result["candidates"]) == 1
    decision = result["candidates"][0]
    assert decision["stage"] == "promotion"
    assert decision["status"] == "promoted"
    promoted = result["promoted"][0]
    assert promoted["kind"] == "fact"
    assert memory.get_fact("name", owner_id="u1") == "John"
    row = memory.get_memory(promoted["id"], scope="user", owner_id="u1")
    assert row["source_ref"] == f"episode:{result['episode_id']}"


def test_low_confidence_candidate_is_not_promoted(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    controller = MemoryIngestionController(memory)
    candidate = MemoryCandidate("fact", "John", key="name", confidence=0.60, importance=4)
    assert controller._validate(candidate)
    episode = memory.add_episode("uncertain", owner_id="u1", session_id="s1")
    decision = controller._process_candidate(candidate, episode_id=episode, owner_id="u1", session_id="s1", run_id=None, auto_promote=True)
    assert decision.status == "rejected"
    assert memory.get_fact("name", owner_id="u1") is None


def test_secret_turn_stays_episodic_but_secret_value_is_redacted(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    result = memory.observe("my password is supersecret", owner_id="u1", session_id="s1")
    assert result["promoted"] == []
    assert result["rejected"]
    assert result["rejected"][0]["reason"] == "secret_material"
    assert memory.profile(owner_id="u1") == []
    assert memory.search_memory("supersecret", owner_id="u1") == []
    episodes = memory.recent_episodes("s1", owner_id="u1")
    assert episodes and "supersecret" not in episodes[0]["user_text"]
    assert "<redacted>" in episodes[0]["user_text"]


def test_identical_candidate_is_deduplicated_not_inserted_twice(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    first = memory.observe("my city is Cairo", owner_id="u1", session_id="s1")
    second = memory.observe("my city is Cairo", owner_id="u1", session_id="s2")
    assert first["promoted"]
    assert second["promoted"]
    assert second["candidates"][0]["status"] == "deduplicated"
    assert second["candidates"][0]["existing_memory_id"] == second["promoted"][0]["id"]
    rows = [r for r in memory.profile(owner_id="u1") if r["key"] == "city"]
    assert len(rows) == 1


def test_conflict_is_detected_then_promoted_as_revision(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    first = memory.observe("my city is Luxor", owner_id="u1", session_id="s1")
    second = memory.observe("my city is Alexandria", owner_id="u1", session_id="s2")
    assert first["promoted"]
    assert second["promoted"]
    assert second["candidates"][0]["conflict"] is True
    assert memory.get_fact("city", owner_id="u1") == "Alexandria"
    history = memory.memory_history(key="city", owner_id="u1", scope="user")
    assert any(item["action"] == "SUPERSEDE" and item["old_value"] == "Luxor" for item in history)


def test_non_fact_candidate_cannot_auto_promote(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    episode = memory.add_episode("I did something", owner_id="u1")
    candidate = MemoryCandidate("note", "I did something", key="note", confidence=0.99)
    decision = MemoryIngestionController(memory)._process_candidate(
        candidate, episode_id=episode, owner_id="u1", session_id=None, run_id=None, auto_promote=True
    )
    assert decision.status == "rejected"
    assert "automatic promotion" in decision.reason

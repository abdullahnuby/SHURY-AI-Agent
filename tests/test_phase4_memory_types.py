from pathlib import Path

import pytest

from app.knowledge.memory import Memory, GLOBAL_SYSTEM, KNOWLEDGE, USER, SESSION, RUN
from app.knowledge.memory_types import (
    WORKING, SESSION_MEMORY, FACT, PREFERENCE, EPISODE, ENTITY, RELATION,
    PROCEDURE, KNOWLEDGE_MEMORY, NOTE, SYSTEM, RUN_MEMORY,
    MEMORY_TYPE_CONTRACTS, CANONICAL_MEMORY_TYPES,
)


def test_phase4_defines_strict_contract_for_every_required_memory_type():
    required = {
        WORKING, SESSION_MEMORY, FACT, PREFERENCE, EPISODE,
        ENTITY, RELATION, PROCEDURE, KNOWLEDGE_MEMORY,
    }
    assert required <= CANONICAL_MEMORY_TYPES
    assert required <= set(MEMORY_TYPE_CONTRACTS)
    for memory_type in required:
        contract = MEMORY_TYPE_CONTRACTS[memory_type]
        assert contract.purpose
        assert contract.storage
        assert contract.allowed_scopes
        assert contract.lifetime
        assert contract.write_policy
        assert contract.read_policy
        assert contract.forget_policy
        assert contract.temporal_policy
        assert isinstance(contract.retrieval_priority, int)


def test_user_fact_preference_note_and_procedure_have_explicit_user_scope(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.remember("John", kind=FACT, key="name", owner_id="u1")
    memory.remember("dark", kind=PREFERENCE, key="theme", owner_id="u1")
    memory.remember("keep this", kind=NOTE, owner_id="u1")
    memory.remember("tool-a -> tool-b", kind=PROCEDURE, key="workflow", owner_id="u1")

    rows = memory.list_memories(scope=USER, owner_id="u1", limit=20)
    assert {row["kind"] for row in rows} == {FACT, PREFERENCE, NOTE, PROCEDURE}

    with pytest.raises(ValueError, match="cannot use scope"):
        memory.remember("bad", kind=FACT, key="x", scope=SESSION, owner_id="u1", session_id="s1")
    with pytest.raises(ValueError, match="requires a canonical key"):
        memory.remember("no key", kind=FACT, owner_id="u1")
    with pytest.raises(ValueError, match="requires a canonical key"):
        memory.remember("no key", kind=PREFERENCE, owner_id="u1")


def test_session_and_run_memory_types_match_their_scopes(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    session_id = memory.remember(
        "session context", kind=SESSION_MEMORY, scope=SESSION, owner_id="u1", session_id="s1"
    )
    run_id = memory.remember(
        "run context", kind=RUN_MEMORY, scope=RUN, owner_id="u1", session_id="s1", run_id="r1"
    )

    assert session_id != run_id
    assert memory.retrieve("session context", scope=SESSION, owner_id="u1", session_id="s1")
    assert memory.retrieve("run context", scope=RUN, owner_id="u1", session_id="s1", run_id="r1")

    with pytest.raises(ValueError, match="cannot use scope"):
        memory.remember("bad", kind=SESSION_MEMORY, scope=USER, owner_id="u1")
    with pytest.raises(ValueError, match="run_id is required"):
        memory.remember("bad", kind=RUN_MEMORY, scope=RUN, owner_id="u1", session_id="s1")


def test_global_system_and_knowledge_types_cannot_be_user_provenanced(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.remember("runtime policy", kind=SYSTEM, scope=GLOBAL_SYSTEM, key="policy", source="system")
    memory.remember("imported document", kind=KNOWLEDGE_MEMORY, scope=KNOWLEDGE, key="doc", source="import")

    assert memory.retrieve("policy", scope=GLOBAL_SYSTEM)
    assert memory.retrieve("doc", scope=KNOWLEDGE)

    with pytest.raises(ValueError, match="cannot be written with user provenance"):
        memory.remember("bad", kind=SYSTEM, scope=GLOBAL_SYSTEM, key="bad")
    with pytest.raises(ValueError, match="cannot be written with user provenance"):
        memory.remember("bad", kind=KNOWLEDGE_MEMORY, scope=KNOWLEDGE, key="bad")


def test_structural_types_have_dedicated_apis_and_cannot_be_smuggled_through_remember(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    for memory_type in (WORKING, EPISODE, ENTITY, RELATION):
        with pytest.raises(ValueError, match="dedicated storage API"):
            memory.remember("bad", kind=memory_type, scope=USER, owner_id="u1", key="x")

    episode_id = memory.record_episode("hello", "hi", owner_id="u1", session_id="s1", run_id="r1")
    working_id = memory.record_working_context("s1", "temporary", owner_id="u1")
    entity_id = memory.link_entity("SHURY", owner_id="u1")
    relation_id = memory.link_relation("SHURY", "type", "agent", owner_id="u1")

    assert episode_id > 0
    assert working_id > 0
    assert entity_id > 0
    assert relation_id > 0


def test_legacy_note_is_still_distinct_from_fact(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.add_note("a general note", owner_id="u1")
    memory.set_fact("name", "John", owner_id="u1")
    rows = memory.list_memories(owner_id="u1", scope=USER, limit=20)
    assert {row["kind"] for row in rows} >= {NOTE, FACT}

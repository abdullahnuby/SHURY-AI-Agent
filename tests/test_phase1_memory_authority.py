from pathlib import Path

import app.knowledge.memory as canonical_memory
import app.knowledge.memory_legacy as legacy_memory


def test_phase1_exposes_one_canonical_memory_authority():
    required = {
        "remember",
        "retrieve",
        "update",
        "correct",
        "forget",
        "record_episode",
        "record_working_context",
        "link_entity",
        "link_relation",
        "consolidate",
        "export",
        "health",
    }

    assert canonical_memory.MemoryAuthority is canonical_memory.Memory
    assert set(canonical_memory.CANONICAL_MEMORY_API) == required
    assert required.issubset(set(dir(canonical_memory.MemoryAuthority)))


def test_legacy_memory_module_is_a_compatibility_alias(tmp_path: Path):
    assert legacy_memory.Memory is canonical_memory.MemoryAuthority
    assert legacy_memory.MemoryAuthority is canonical_memory.MemoryAuthority
    assert legacy_memory.configure is canonical_memory.configure
    assert legacy_memory.get_memory is canonical_memory.get_memory

    memory = legacy_memory.Memory(tmp_path / "memory.db")
    memory.remember("Abdullah", kind="fact", key="name")

    assert memory.retrieve("name", kinds={"fact"})


def test_canonical_operations_share_the_same_authority_store(tmp_path: Path):
    memory = canonical_memory.MemoryAuthority(tmp_path / "memory.db")

    first = memory.remember("Cairo", kind="fact", key="city", source="user")
    second = memory.update("Giza", kind="fact", key="city", source="user")
    corrected = memory.correct("Alexandria", kind="fact", key="city", source="user")

    assert first != second != corrected
    hits = memory.retrieve("city", kinds={"fact"}, top_k=5)
    assert hits and hits[0]["value"] == "Alexandria"

    episode_id = memory.record_episode(
        "We decided the deployment plan.",
        "Plan recorded.",
        outcome="completed",
        session_id="session-1",
        run_id="run-1",
    )
    working_id = memory.record_working_context("session-1", "current task", priority=5)
    entity_id = memory.link_entity("SHURY", aliases=("Shury",))
    relation_id = memory.link_relation("SHURY", "type", "agent")

    assert episode_id > 0
    assert working_id > 0
    assert entity_id > 0
    assert relation_id > 0
    assert memory.health()["ok"] is True
    assert memory.export(include_history=True, include_episodes=True)["schema"] == "personal-agent.memory.v1"


def test_legacy_method_names_delegate_to_canonical_names(tmp_path: Path):
    memory = canonical_memory.MemoryAuthority(tmp_path / "memory.db")

    memory.remember("persistent value", kind="fact", key="sample")

    legacy_hits = memory.search_memory("sample", kinds={"fact"})
    canonical_hits = memory.retrieve("sample", kinds={"fact"})
    assert [(h["id"], h["kind"], h["key"], h["value"]) for h in legacy_hits] == [
        (h["id"], h["kind"], h["key"], h["value"]) for h in canonical_hits
    ]

    legacy_episode = memory.add_episode("hello", "hi", session_id="s")
    canonical_episode = memory.record_episode("hello again", "hi again", session_id="s")
    assert canonical_episode > legacy_episode

    assert memory.working_put("s", "legacy context") > 0
    assert memory.working_recall("s")

    assert memory.upsert_entity("legacy entity") > 0
    assert memory.relate("legacy entity", "kind", "test") > 0
    assert memory.memory_health()["ok"] is True
    assert memory.export_memory()["schema"] == memory.export()["schema"]

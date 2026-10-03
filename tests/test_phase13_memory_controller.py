from __future__ import annotations

from pathlib import Path

from app.brain.kernel import CognitiveKernel
from app.brain.models import Evidence, SemanticFrame
from app.knowledge.memory import Memory
from app.knowledge.memory_controller import MemoryController, MemoryEvidence, MemoryEvidenceBundle
from app.intelligence.semantic import semantic_understand


def test_controller_returns_structured_memory_evidence_and_hides_storage_shape(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db", owner_id="u1")
    memory.remember("Cairo", kind="fact", key="city", scope="user", owner_id="u1")
    controller = MemoryController(memory)
    frame = semantic_understand("what is my city?", mem=memory, session_id="s1")
    bundle = controller.retrieve_for_frame(frame, owner_id="u1", session_id="s1")
    assert isinstance(bundle, MemoryEvidenceBundle)
    assert bundle.requirement.need == "user_fact"
    assert bundle.evidence
    assert all(isinstance(item, MemoryEvidence) for item in bundle.evidence)
    assert bundle.to_brain_evidence()[0].kind == "memory"
    assert bundle.to_brain_evidence()[0].reference.startswith("fact:")
    assert not any("sql" in key.lower() for item in bundle.evidence for key in item.metadata)


def test_controller_handles_episode_and_knowledge_as_distinct_lanes(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db", owner_id="u1")
    memory.record_episode("What did we do?", "We fixed the issue.", summary="fixed issue", owner_id="u1", session_id="s1", run_id="r1")
    memory.remember("approved project standard", kind="knowledge", key="standard", scope="knowledge", source="document")
    controller = MemoryController(memory)

    episode_frame = semantic_understand("what did we do in the previous task?", mem=memory, session_id="s1")
    episode_bundle = controller.retrieve_for_frame(episode_frame, owner_id="u1", session_id="s1")
    assert episode_bundle.requirement.need == "episodic"
    assert episode_bundle.evidence
    assert {item.memory_type for item in episode_bundle.evidence} == {"episode"}

    knowledge_frame = SemanticFrame(
        text="what is the approved project standard?", language="en", speech_act="question",
        requested_operation="query_knowledge", memory_need="knowledge", memory_types=("knowledge",),
        memory_reason="world/project information requires knowledge evidence",
    )
    knowledge_bundle = controller.retrieve_for_frame(knowledge_frame, owner_id="u1", session_id="s1")
    assert knowledge_bundle.requirement.need == "knowledge"
    assert knowledge_bundle.evidence
    assert {item.memory_type for item in knowledge_bundle.evidence} == {"knowledge"}


def test_brain_retrieve_uses_controller_not_memory_storage_calls(tmp_path: Path, monkeypatch):
    memory = Memory(tmp_path / "memory.db", owner_id="u1")
    kernel = CognitiveKernel(memory=memory)
    state = kernel.perceive("what is my city?", session_id="s1")

    original_controller = kernel.memory_controller

    class StubController:
        def retrieve_for_frame(self, frame, *, owner_id=None, session_id=None, run_id=None, limit=8):
            assert frame.memory_need == "user_fact"
            return MemoryEvidenceBundle(
                requirement=original_controller.requirement_from(frame),
                evidence=(MemoryEvidence("fact", "city = Cairo", 1.0, 1.0, "test", "fact:city", "test"),),
                scope="user",
                selected_stores=("durable_user_memory",),
            )

        def profile_evidence(self, **kwargs):
            return MemoryEvidenceBundle(requirement=original_controller.requirement_from(state.semantic), evidence=())

    monkeypatch.setattr(kernel, "memory_controller", StubController())
    monkeypatch.setattr(memory, "recall_context", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Brain must not call storage retrieval directly")))
    monkeypatch.setattr(memory, "get_fact", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Brain must not call get_fact directly during retrieval")))
    kernel.retrieve(state)
    assert state.evidence
    assert isinstance(state.evidence[0], Evidence)
    assert state.evidence[0].content == "city = Cairo"


def test_brain_belief_projection_uses_controller_boundary(tmp_path: Path, monkeypatch):
    memory = Memory(tmp_path / "memory.db", owner_id="u1")
    memory.remember("Cairo", kind="fact", key="city", scope="user", owner_id="u1")
    kernel = CognitiveKernel(memory=memory)
    bundle = kernel.memory_controller.profile_evidence(owner_id="u1", session_id="s1")
    assert bundle.evidence
    original_controller = kernel.memory_controller

    class StubController:
        def profile_evidence(self, **kwargs):
            return bundle

        def retrieve_for_frame(self, *args, **kwargs):
            return original_controller.retrieve_for_frame(*args, **kwargs)

    monkeypatch.setattr(kernel, "memory_controller", StubController())
    monkeypatch.setattr(memory, "profile", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Brain must not call profile directly")))
    beliefs = kernel._load_beliefs("s1")
    assert beliefs and beliefs[0].predicate == "city"


def test_cognitive_context_uses_structured_controller(tmp_path: Path):
    from app.intelligence.cognitive.context import memory_context

    memory = Memory(tmp_path / "memory.db", owner_id="u1")
    memory.remember("Cairo", kind="fact", key="city", scope="user", owner_id="u1")
    payload = memory_context(memory, "city", session_id="s1")
    assert payload["memory_requirement"]["need"] == "mixed_personal"
    assert payload["evidence"]
    assert all("memory_type" in item for item in payload["evidence"])
    assert "semantic" not in payload
    assert "episodic" not in payload

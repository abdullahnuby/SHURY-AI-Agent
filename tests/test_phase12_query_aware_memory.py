from pathlib import Path

from app.brain.kernel import CognitiveKernel
from app.intelligence.semantic.contract import from_parse
from app.intelligence.semantic.parser import semantic_understand
from app.knowledge.memory import Memory
from app.knowledge.memory_query import plan_memory_query
from app.knowledge.memory_types import USER


def test_identity_question_routes_only_to_user_fact_lane():
    plan = plan_memory_query("what is my name?", intent="recall_fact")
    assert plan.need == "user_fact"
    assert set(plan.memory_types) == {"fact", "preference", "note"}
    assert set(plan.memory_types).isdisjoint({"episode", "procedural", "knowledge", "entity", "relation", "working"})


def test_previous_task_routes_to_episodic_only():
    plan = plan_memory_query("what did we do in the previous task?", intent="memory_search")
    assert plan.need == "episodic"
    assert plan.memory_types == ("episode",)


def test_how_we_solved_routes_to_procedure_and_experience():
    plan = plan_memory_query("how did we solve the migration issue?", intent="memory_search")
    assert plan.need == "procedural_experience"
    assert set(plan.memory_types) == {"procedural", "episode"}


def test_latest_info_routes_to_knowledge_not_personal_memory():
    plan = plan_memory_query("what is the latest information about X?", intent="query_knowledge")
    assert plan.need == "knowledge"
    assert plan.memory_types == ("knowledge",)


def test_non_memory_turn_has_no_memory_requirement():
    plan = plan_memory_query("calculate 2+2", intent="calculate")
    assert plan.need == "none"
    assert plan.memory_types == ()


def test_semantic_parse_emits_memory_requirement():
    parsed = semantic_understand("what do you remember about me?", mem=Memory(":memory:"))
    assert parsed.memory_need == "user_fact"
    assert set(parsed.memory_types) == {"fact", "preference", "note"}
    contract = from_parse(parsed)
    assert contract.memory_need == parsed.memory_need
    assert tuple(contract.memory_types) == tuple(parsed.memory_types)


def test_memory_recall_does_not_fan_out_to_unselected_stores(tmp_path: Path, monkeypatch):
    m = Memory(tmp_path / "m.db")
    m.remember("Abdullah", kind="fact", key="name", scope=USER, owner_id="u1")
    m.record_episode("we discussed a secret project", "done", owner_id="u1", session_id="s1")
    m.remember("verified procedure", kind="procedural", key="migration", scope=USER, owner_id="u1")
    m.remember("knowledge text", kind="knowledge", key="doc1", scope="knowledge", source="import")

    calls = []
    original_retrieve = m.retrieve
    original_episodes = m.retrieve_episodes
    original_procedure = m.procedural_memory
    original_working = m.working_recall

    def retrieve(*args, **kwargs):
        calls.append(("retrieve", kwargs.get("kinds")))
        return original_retrieve(*args, **kwargs)

    def episodes(*args, **kwargs):
        calls.append(("episodes", None))
        return original_episodes(*args, **kwargs)

    def procedure(*args, **kwargs):
        calls.append(("procedure", None))
        return original_procedure(*args, **kwargs)

    def working(*args, **kwargs):
        calls.append(("working", None))
        return original_working(*args, **kwargs)

    monkeypatch.setattr(m, "retrieve", retrieve)
    monkeypatch.setattr(m, "retrieve_episodes", episodes)
    monkeypatch.setattr(m, "procedural_memory", procedure)
    monkeypatch.setattr(m, "working_recall", working)

    ctx = m.recall_context(
        "what did we do in the previous task?",
        owner_id="u1",
        session_id="s1",
        intent="memory_search",
    )
    assert ctx["memory_plan"]["need"] == "episodic"
    assert any(kind == "episodes" for kind, _ in calls)
    assert not any(kind == "procedure" for kind, _ in calls)
    assert not any(kind == "working" for kind, _ in calls)
    assert not any(kind == "retrieve" for kind, _ in calls)


def test_memory_recall_plan_can_be_passed_from_semantic_frame(tmp_path: Path):
    m = Memory(tmp_path / "m.db")
    parsed = semantic_understand("what did we do in the previous task?", mem=m, session_id="s1")
    ctx = m.recall_context(
        parsed.original,
        owner_id="u1",
        session_id="s1",
        memory_plan={
            "need": parsed.memory_need,
            "memory_types": list(parsed.memory_types),
            "stores": ["episodic"],
            "rationale": parsed.memory_reason,
            "confidence": parsed.confidence,
        },
    )
    assert ctx["memory_plan"]["need"] == parsed.memory_need
    assert ctx["semantic"] == []
    assert ctx["episodic"] == []


def test_brain_frame_carries_memory_requirement(tmp_path: Path, monkeypatch):
    m = Memory(tmp_path / "m.db")
    kernel = CognitiveKernel(memory=m)
    state = kernel.perceive("what did we do in the previous task?", session_id="s1")
    assert state.semantic is not None
    assert state.semantic.memory_need == "episodic"
    assert state.semantic.memory_types == ("episode",)


def test_knowledge_query_reads_knowledge_scope_without_personal_memory(tmp_path: Path, monkeypatch):
    m = Memory(tmp_path / "m.db")
    m.remember("project architecture specification", kind="knowledge", key="spec", scope="knowledge", source="import")
    m.remember("personal architecture preference", kind="note", key="preference", scope=USER, owner_id="u1")
    calls = []
    original = m.retrieve

    def retrieve(*args, **kwargs):
        calls.append(kwargs.copy())
        return original(*args, **kwargs)

    monkeypatch.setattr(m, "retrieve", retrieve)
    ctx = m.recall_context("project architecture specification", owner_id="u1", session_id="s1", intent="query_knowledge")
    assert ctx["memory_plan"]["need"] == "knowledge"
    assert ctx["knowledge"] and ctx["knowledge"][0]["kind"] == "knowledge"
    assert ctx["semantic"] == []
    assert any(c.get("scope") == "knowledge" and c.get("owner_id") is None for c in calls)


def test_current_task_can_prioritize_working_context():
    plan = plan_memory_query("check this task", intent="memory_search")
    assert plan.need == "working_context"
    assert set(plan.memory_types) == {"working", "episode"}


def test_semantic_parser_does_not_eagerly_fan_out_memory_recall():
    class NoRecallMemory(Memory):
        def recall_context(self, *args, **kwargs):
            raise AssertionError("semantic parser must not retrieve memory before establishing a semantic need")

    parsed = semantic_understand("what is my name?", mem=NoRecallMemory(":memory:"))
    assert parsed.memory_need == "user_fact"


from pathlib import Path

import pytest

from app.knowledge.knowledge_base import KnowledgeBase
from app.knowledge.memory import Memory, KNOWLEDGE
from app.knowledge.rag import RAGEngine


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_personal_memory_indexing_is_blocked_and_does_not_create_rag_memory_files(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.set_fact("name", "John", owner_id="u1")
    rag = RAGEngine(tmp_path / "rag.db")

    result = rag.index_memory(memory.path)

    assert result["blocked"] is True
    assert result["indexed"] == 0
    assert not (tmp_path / ".rag_memory").exists()
    assert not rag.list_knowledge()


def test_knowledge_file_has_explicit_provenance_and_scope(tmp_path: Path):
    rag = RAGEngine(tmp_path / "rag.db")
    source = _write(tmp_path / "project.md", "The KEMEX project logistics policy requires signed delivery evidence.")

    out = rag.index_knowledge(source, project_id="kemex", provenance={"origin": "project_file", "source_kind": "document"})
    rows = rag.list_knowledge(project_id="kemex")

    assert out["knowledge"]["indexed"] == 1
    assert rows and rows[0]["knowledge_scope"] == "project"
    assert rows[0]["project_id"] == "kemex"
    assert rows[0]["source_ref"]
    assert rows[0]["provenance"]["origin"] == "project_file"
    assert rows[0]["provenance"]["source_kind"] == "document"


def test_world_knowledge_is_visible_without_project_and_to_projects(tmp_path: Path):
    rag = RAGEngine(tmp_path / "rag.db")
    source = _write(tmp_path / "world.md", "The international logistics standard defines delivery evidence requirements.")
    rag.index_knowledge(source, provenance={"origin": "verified_reference", "source_kind": "document"})

    all_rows = rag.list_knowledge()
    project_rows = rag.list_knowledge(project_id="project-a")

    assert all_rows and all_rows[0]["knowledge_scope"] == "world"
    assert project_rows and project_rows[0]["knowledge_scope"] == "world"


def test_project_knowledge_isolated_from_other_projects(tmp_path: Path):
    rag = RAGEngine(tmp_path / "rag.db")
    a = _write(tmp_path / "a.md", "PROJECT_A_ONLY secret phrase delivery corridor Alpha-One.")
    b = _write(tmp_path / "b.md", "PROJECT_B_ONLY secret phrase delivery corridor Beta-Two.")
    rag.index_knowledge(a, project_id="A", provenance={"origin": "project_a", "source_kind": "document"}, source_ref="project:A")
    rag.index_knowledge(b, project_id="B", provenance={"origin": "project_b", "source_kind": "document"}, source_ref="project:B")

    a_result = rag.query("PROJECT_A_ONLY delivery corridor", project_id="A", top_k=5)
    b_result = rag.query("PROJECT_B_ONLY delivery corridor", project_id="B", top_k=5)
    a_text = " ".join(r["text"] for r in a_result["retrieval"])
    b_text = " ".join(r["text"] for r in b_result["retrieval"])

    assert "PROJECT_A_ONLY" in a_text
    assert "PROJECT_B_ONLY" not in a_text
    assert "PROJECT_B_ONLY" in b_text
    assert "PROJECT_A_ONLY" not in b_text


def test_knowledge_retrieval_carries_provenance(tmp_path: Path):
    rag = RAGEngine(tmp_path / "rag.db")
    source = _write(tmp_path / "ref.md", "A verified reference says signed proof of delivery is retained.")
    rag.index_knowledge(source, provenance={"origin": "verified_reference", "source_kind": "document"}, source_ref="ref:pod")

    out = rag.query("signed proof of delivery", top_k=3)
    assert out["retrieval"]
    hit = out["retrieval"][0]
    assert hit["knowledge_scope"] == "world"
    assert hit["source_ref"] == "ref:pod"
    assert hit["provenance"]["origin"] == "verified_reference"


def test_knowledge_can_be_removed_without_touching_personal_memory(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.set_fact("name", "John", owner_id="u1")
    kb = KnowledgeBase(RAGEngine(tmp_path / "rag.db"))
    source = _write(tmp_path / "doc.md", "A world document says the transport permit requires inspection.")
    kb.add(source, provenance={"origin": "local_reference", "source_kind": "document"})

    assert kb.get(str(source.resolve())) is not None
    assert kb.remove(str(source.resolve())) is True
    assert kb.get(str(source.resolve())) is None
    assert memory.get_fact("name", owner_id="u1") == "John"


def test_knowledge_base_supports_user_managed_text_without_python_source_changes(tmp_path: Path):
    kb = KnowledgeBase(RAGEngine(tmp_path / "rag.db"))
    kb.add_text("knowledge:manual:v1", "Manual", "The maintenance manual requires a signed inspection record.",
                project_id="fleet-1", provenance={"origin": "user_import", "source_kind": "manual"})

    listed = kb.list(project_id="fleet-1")
    assert listed and listed[0]["source_ref"] == "knowledge:manual:v1"
    assert listed[0]["project_id"] == "fleet-1"
    assert kb.remove("knowledge:manual:v1", project_id="fleet-1") is True
    assert kb.list(project_id="fleet-1") == []


def test_knowledge_memory_scope_stays_out_of_user_memory_queries(tmp_path: Path):
    memory = Memory(tmp_path / "memory.db")
    memory.remember(
        "Imported project rule",
        kind="knowledge",
        scope=KNOWLEDGE,
        key="project-rule",
        source="import",
        source_ref="knowledge:project-rule",
        metadata={"origin": "project_document", "source_kind": "document", "source_ref": "knowledge:project-rule"},
    )
    memory.set_fact("rule", "Personal rule", owner_id="u1")

    user_hits = memory.retrieve("project rule", scope="user", owner_id="u1")
    knowledge_hits = memory.retrieve("project rule", scope=KNOWLEDGE)

    assert not any(h["key"] == "project-rule" for h in user_hits)
    assert any(h["key"] == "project-rule" for h in knowledge_hits)


def test_knowledge_provenance_is_required_for_knowledge_base_sources(tmp_path: Path):
    rag = RAGEngine(tmp_path / "rag.db")
    source = _write(tmp_path / "doc.md", "Evidence text.")
    with pytest.raises(ValueError, match="provenance/source_ref"):
        rag._annotate_knowledge_sources(paths=[str(source.resolve())], provenance={}, source_ref="")


def test_knowledge_stats_are_project_scoped(tmp_path: Path):
    rag = RAGEngine(tmp_path / "rag.db")
    _write(tmp_path / "world.md", "world evidence")
    _write(tmp_path / "project.md", "project evidence")
    rag.index_knowledge(tmp_path / "world.md", provenance={"origin": "world", "source_kind": "document"})
    rag.index_knowledge(tmp_path / "project.md", project_id="P1", provenance={"origin": "project", "source_kind": "document"})

    p1 = rag.knowledge_stats(project_id="P1")
    p2 = rag.knowledge_stats(project_id="P2")
    assert p1["sources"] == 2
    assert p2["sources"] == 1


def test_external_knowledge_gets_provenance_and_is_not_personal_memory(tmp_path: Path):
    rag = RAGEngine(tmp_path / "rag.db")
    rag.index_knowledge_text(
        "https://example.org/manual",
        "Manual",
        "The manual requires two signatures.",
        provenance={"origin": "verified_external", "source_kind": "web"},
    )
    row = rag.list_knowledge()[0]
    assert row["knowledge_scope"] == "world"
    assert row["source_ref"] == "https://example.org/manual"
    assert row["provenance"]["origin"] == "verified_external"


def test_adaptive_rag_preserves_project_scope_and_provenance(tmp_path: Path):
    from app.knowledge.rag_v16 import AdaptiveRAGEngine
    rag = RAGEngine(tmp_path / "rag.db")
    a = _write(tmp_path / "adaptive_a.md", "ADAPTIVE_PROJECT_A evidence about dispatch routing Alpha.")
    b = _write(tmp_path / "adaptive_b.md", "ADAPTIVE_PROJECT_B evidence about dispatch routing Beta.")
    rag.index_knowledge(a, project_id="A", provenance={"origin": "project_a", "source_kind": "document"}, source_ref="adaptive:A")
    rag.index_knowledge(b, project_id="B", provenance={"origin": "project_b", "source_kind": "document"}, source_ref="adaptive:B")

    out = AdaptiveRAGEngine(db_path=rag.db_path).query("ADAPTIVE_PROJECT_A dispatch routing", top_k=4, max_strategies=2, project_id="A")
    text = " ".join(r["text"] for r in out["retrieval"])
    assert "ADAPTIVE_PROJECT_A" in text
    assert "ADAPTIVE_PROJECT_B" not in text
    assert all(r["project_id"] == "A" for r in out["retrieval"])
    assert all(r["provenance"].get("origin") == "project_a" for r in out["retrieval"])

from app.knowledge.agentic_rag.orchestrator import AgenticRAGEngine
from app.intelligence.semantic.parser import SemanticInterpreter


class EmptyRAG:
    def __init__(self): self.calls = []
    def query(self, q, top_k=6, max_strategies=3):
        self.calls.append(q)
        return {"evidence": []}


class RecoveryWeb:
    def __init__(self): self.calls = []
    def research(self, q, limit=5, index=True):
        self.calls.append(q)
        return {"sources": [{
            "title": "Primary policy",
            "url": "https://www.example.gov/policy",
            "text": "The current policy requires operator approval before production deployment. The rule applies to all production releases.",
            "sha256": "hash", "score": 0.95, "source_quality": 1.0, "indexed": True,
        }]}


def test_local_failure_escalates_to_web():
    web = RecoveryWeb()
    out = AgenticRAGEngine(rag=EmptyRAG(), web=web).query("what is the current policy?", max_rounds=1)
    assert web.calls
    assert out["evidence"]
    assert out["evidence"][0]["source_kind"] == "web"


def test_agentic_rag_preserves_numeric_claims():
    class R:
        def query(self, q, top_k=6, max_strategies=3):
            return {"evidence": [{"title": "Report", "source": "file://report", "text": "Revenue increased by 34% during 2026.", "chunk_id": 1, "score": 0.95}]}
    out = AgenticRAGEngine(rag=R(), web=RecoveryWeb()).query("revenue increased by 34%", max_rounds=1)
    assert out["outcome"] == "answered"
    assert "34%" in out["answer"]
    assert out["verification"]["claims_verified"] >= 1


def test_agentic_rag_is_extractively_synthesized():
    class R:
        def query(self, q, top_k=6, max_strategies=3):
            return {"evidence": [{"title": "Guide", "source": "file://guide", "text": "Production requires operator approval before release.", "chunk_id": 1, "score": 0.95}]}
    out = AgenticRAGEngine(rag=R(), web=RecoveryWeb()).query("operator approval for production", max_rounds=1)
    assert out["synthesis_mode"] == "extractive"
    assert out["claims"]
    assert "Production requires operator approval" in out["answer"]


def test_semantic_layer_routes_agentic_rag():
    parsed = SemanticInterpreter().parse("search iteratively and verify evidence with agentic rag")
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == "agentic_rag"

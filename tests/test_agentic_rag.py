from pathlib import Path
from app.knowledge.agentic_rag.orchestrator import AgenticRAGEngine
from app.knowledge.agentic_rag.router import build_plan
from app.knowledge.agentic_rag.evidence import claim_support_score, detect_conflicts


class FakeRAG:
    def __init__(self):
        self.calls = []
    def query(self, q, top_k=6, max_strategies=3):
        self.calls.append(q)
        if "deployment" in q.lower():
            return {"evidence": [{"title": "Guide", "source": "file://guide", "text": "Production deployment requires operator approval. Operators review the deployment before release.", "chunk_id": 1, "score": 0.9}]}
        return {"evidence": []}


class FakeWeb:
    def __init__(self):
        self.calls = []
    def research(self, q, limit=5, index=True):
        self.calls.append(q)
        return {"sources": [{"title": "Current source", "url": "https://example.org/current", "text": "The current policy requires operator approval for production deployment.", "sha256": "x", "score": 0.9, "source_quality": 0.86, "indexed": True}]}


def test_router_distinguishes_local_web_hybrid():
    assert build_plan("what is in the indexed documents?").route == "local"
    assert build_plan("what is the latest policy online?").route == "web"
    assert build_plan("compare the latest policy with the indexed documents").route == "hybrid"


def test_agentic_rag_iterates_and_returns_verified_citations():
    engine = AgenticRAGEngine(rag=FakeRAG(), web=FakeWeb())
    out = engine.query("agentic rag deployment approval", max_rounds=2)
    assert out["outcome"] in {"answered", "partial"}
    assert out["evidence"]
    assert out["claims"]
    assert out["verification"]["all_citations_valid"]
    assert "[E001]" in out["answer"]


def test_agentic_rag_web_route_uses_external_evidence():
    engine = AgenticRAGEngine(rag=FakeRAG(), web=FakeWeb())
    out = engine.query("what is the latest policy online?", max_rounds=1)
    assert out["evidence"]
    assert out["evidence"][0]["source_kind"] == "web"


def test_claim_numeric_support_is_strict():
    assert claim_support_score("revenue is 34%", "revenue is 34% this year") > 0.9
    assert claim_support_score("revenue is 47%", "revenue is 34% this year") < 0.5


def test_conflict_detector_reports_numeric_disagreement():
    a = {"evidence_id": "E001", "source_kind": "web", "url": "https://a.org", "text": "Revenue was 34% higher."}
    b = {"evidence_id": "E002", "source_kind": "web", "url": "https://b.org", "text": "Revenue was 47% higher."}
    conflicts = detect_conflicts([], [a, b])
    assert conflicts and conflicts[0]["type"] == "numeric"

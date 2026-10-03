from __future__ import annotations
from tempfile import TemporaryDirectory
from pathlib import Path
from app.knowledge.rag import RAGEngine
from app.knowledge.rag_v16 import AdaptiveRAGEngine
from app.knowledge.agentic_rag.orchestrator import AgenticRAGEngine


class _Web:
    def __init__(self):
        self.calls = []
    def research(self, query, limit=5, index=True):
        self.calls.append(query)
        return {"sources": [{
            "title": "Primary evidence",
            "url": "https://example.gov/policy",
            "text": "Production deployment requires operator approval. The approval rule applies to production releases.",
            "sha256": "bench-policy",
            "score": 0.95,
            "source_quality": 1.0,
            "indexed": True,
        }]}


def run_agentic_rag_benchmark() -> dict:
    cases = []
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "guide.md").write_text(
            "# Deployment\n\nProduction deployment requires operator approval.\n\n"
            "# Incident\n\nCritical incidents must be written to the log.\n", encoding="utf-8"
        )
        base = RAGEngine(root / "rag.db")
        base.index(root)
        web = _Web()
        engine = AgenticRAGEngine(rag=AdaptiveRAGEngine(root / "rag.db"), web=web)

        local = engine.query("what requires operator approval for production deployment?", max_rounds=1)
        cases.append(("local grounded answer", local["outcome"] == "answered" and local["claims"] and local["verification"]["all_citations_valid"]))

        web_out = engine.query("what is the latest production approval policy online?", max_rounds=1)
        cases.append(("web current route", bool(web.calls) and web_out["evidence"] and web_out["evidence"][0]["source_kind"] == "web"))

        empty_web = _Web()
        empty = AgenticRAGEngine(rag=AdaptiveRAGEngine(root / "empty.db"), web=empty_web).query("unicorn policy", max_rounds=1)
        cases.append(("fail closed", empty["outcome"] == "abstained" and not empty["claims"]))

        comparison = engine.query("deployment approval and incident log", max_rounds=2)
        cases.append(("multi need coverage", len(comparison["plan"]["subquestions"]) == 2 and comparison["trace"]))

    passed = sum(bool(ok) for _, ok in cases)
    return {"passed": passed, "total": len(cases), "accuracy": passed / max(1, len(cases)),
            "cases": [{"name": n, "passed": bool(ok)} for n, ok in cases]}

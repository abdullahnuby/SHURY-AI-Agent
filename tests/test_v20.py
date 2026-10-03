from pathlib import Path
from tempfile import TemporaryDirectory

from app.knowledge.open_world import OpenWorldResearchEngine
from app.knowledge.research_memory import ResearchMemory
from app.evaluation.versions.v20 import run_v20_benchmark


class FakeResearch:
    def internet_research(self, query, web_limit=6, paper_limit=8, repo_limit=6, index=True, providers=("web", "arxiv", "github")):
        assert set(providers) == {"web", "arxiv", "github"}
        return {
            "query": query,
            "web": {"sources": [{"title": "Docs", "url": "https://example.com/docs", "sha256": "a" * 64,
                                  "snippet": "adaptive retrieval algorithm", "score": 0.8, "indexed": True}]},
            "arxiv": {"papers": [{"title": "Adaptive RAG", "url": "https://arxiv.org/abs/1234",
                                     "abstract": "agentic retrieval and adaptive search", "published": "2026-09-01", "indexed": True}]},
            "github": {"repositories": [{"full_name": "demo/agent", "html_url": "https://github.com/demo/agent",
                                            "description": "agentic rag implementation", "updated_at": "2026-09-10",
                                            "stargazers_count": 5}]},
        }


def test_v20_open_world_learning_persists_provenance_and_source_policy(tmp_path):
    memory = ResearchMemory(tmp_path / "research.db")
    out = OpenWorldResearchEngine(research=FakeResearch(), memory=memory).learn("latest adaptive RAG algorithm implementation")
    assert out["run_id"] > 0
    assert set(x["source"] for x in out["route"]) == {"web", "arxiv", "github"}
    assert memory.stats()["runs"] == 1
    assert memory.stats()["evidence_items"] >= 3
    assert tuple(out["candidate_skill"]["workflow"]) == ()
    assert memory.related("adaptive retrieval")
    assert len(memory.source_stats("latest adaptive RAG algorithm implementation")) >= 3


def test_v20_benchmark_green():
    out = run_v20_benchmark()
    assert out["passed"] == out["total"]

from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3

from app.knowledge.research_memory import ResearchMemory
from app.knowledge.open_world import OpenWorldResearchEngine


class FakeResearch:
    def internet_research(self, query, web_limit=6, paper_limit=8, repo_limit=6, index=True, providers=("web", "arxiv", "github")):
        return {
            "query": query,
            "web": {"sources": [{"title": "Docs", "url": "https://example.com/docs", "sha256": "a"*64, "snippet": "adaptive retrieval algorithm", "score": 0.8, "indexed": True}]},
            "arxiv": {"papers": [{"title": "Adaptive RAG", "url": "https://arxiv.org/abs/1234", "abstract": "agentic retrieval and adaptive search", "published": "2026-09-01", "indexed": True}]},
            "github": {"repositories": [{"full_name": "demo/agent", "html_url": "https://github.com/demo/agent", "description": "agentic rag implementation", "updated_at": "2026-09-10", "stargazers_count": 5}]},
        }


def run_v20_benchmark():
    cases=[]
    with TemporaryDirectory(prefix="agent-v20-bench-") as td:
        mem=ResearchMemory(Path(td)/"research.db")
        engine=OpenWorldResearchEngine(research=FakeResearch(), memory=mem)
        out=engine.learn("latest adaptive RAG algorithm implementation")
        cases.append(("multi_source_route", {x["source"] for x in out["route"]} >= {"arxiv","github","web"}))
        cases.append(("evidence_persisted", mem.stats()["evidence_items"] >= 3))
        cases.append(("newness_signal", out["new_evidence_count"] >= 1))
        cases.append(("declarative_candidate", bool(out["candidate_skill"]) and not out["candidate_skill"].get("workflow")))
        related=mem.related("adaptive retrieval",limit=5)
        cases.append(("related_evidence", len(related) >= 1))
        stats=mem.source_stats("latest adaptive RAG algorithm implementation")
        cases.append(("source_utility_memory", len(stats) >= 3))
        # Durability across a reopened DB.
        reopened=ResearchMemory(Path(td)/"research.db")
        cases.append(("durable_memory", reopened.stats()["runs"] == 1 and reopened.stats()["evidence_items"] >= 3))
    passed=sum(1 for _, ok in cases if ok)
    return {"passed":passed,"total":len(cases),"cases":[{"name":n,"passed":bool(ok)} for n,ok in cases]}

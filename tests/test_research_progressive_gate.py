from pathlib import Path


def test_research_topic_strips_workflow_language():
    from app.knowledge.web_research import _research_topic
    topic = _research_topic(
        "ابحث على الإنترنت عن أحدث 5 أبحاث موثوقة خلال آخر سنتين عن Long-Term Memory للـAI Agents. "
        "قارن بينها واختر أفضل معماريتين ثم احفظ النتيجة في workspace/agent_memory_research.md"
    )
    normalized = topic.casefold()
    assert "long" in normalized
    assert "memory" in normalized
    assert "agents" in normalized
    assert "workspace" not in normalized
    assert "compare" not in normalized


def test_arxiv_research_filters_unrelated_latest_results(monkeypatch, tmp_path):
    from app.knowledge.web_research import WebResearchEngine

    class FakeGateway:
        def arxiv_search(self, query, limit=12):
            assert 'all:"memory"' in query.lower()
            return [
                {
                    "rank": 1, "title": "Unrelated 3D Graphics", "url": "https://arxiv.org/abs/u",
                    "abstract": "3D rendering and geometry with animation.", "published": "2026-10-01T00:00:00Z",
                    "updated": "2026-10-01T00:00:00Z", "authors": ["A"], "source": "arxiv"
                },
                {
                    "rank": 2, "title": "Long-Term Memory for AI Agents", "url": "https://arxiv.org/abs/r",
                    "abstract": "We study agent memory, long-term memory, retrieval, temporal updates, forgetting and experience learning.",
                    "published": "2026-09-01T00:00:00Z", "updated": "2026-09-01T00:00:00Z", "authors": ["B"], "source": "arxiv"
                },
                {
                    "rank": 3, "title": "Memory Agents with Hybrid Retrieval", "url": "https://arxiv.org/abs/r2",
                    "abstract": "AI agent memory with episodic retrieval, temporal history and selective forgetting.",
                    "published": "2026-08-01T00:00:00Z", "updated": "2026-08-01T00:00:00Z", "authors": ["C"], "source": "arxiv"
                },
            ]

    class FakeRAG:
        def index_knowledge_text(self, *args, **kwargs):
            return True

    engine = WebResearchEngine(gateway=FakeGateway(), rag=FakeRAG())
    result = engine.arxiv_research("Long-Term Memory for AI Agents", limit=2, index=True)
    assert result["candidate_count"] == 3
    assert result["count"] == 2
    assert all("3D Graphics" not in p["title"] for p in result["papers"])
    assert result["relevance_gate"]["qualifying"] == 2


def test_report_refuses_to_claim_five_papers_without_five_relevant_sources(monkeypatch, tmp_path):
    from app.tools.research.report import create_research_report

    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    papers = [
        {
            "title": "Long-Term Agent Memory", "authors": ["A"], "published": "2026-09-01T00:00:00Z",
            "url": "https://arxiv.org/abs/a", "abstract": "agent memory retrieval temporal forgetting experience",
            "relevance": 0.9,
        }
        for _ in range(3)
    ]
    wrapped = create_research_report.run(
        research_result={"providers": ["arxiv"], "arxiv": {"papers": papers, "relevance_gate": {"threshold": 0.18}}},
        output_path="agent_memory_research.md",
        question="find the latest 5 papers about long-term memory for AI agents",
    )
    assert wrapped.ok is False
    assert "required at least 5 relevant papers" in str(wrapped.error)
    assert not (Path(tmp_path) / "agent_memory_research.md").exists()


def test_report_accepts_five_relevant_sources(monkeypatch, tmp_path):
    from app.tools.research.report import create_research_report
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    papers = [
        {
            "title": f"Long-Term Agent Memory {i}", "authors": ["A"], "published": f"2026-0{i+1}-01T00:00:00Z",
            "url": f"https://arxiv.org/abs/{i}",
            "abstract": "agent memory retrieval temporal forgetting experience learning graph", "relevance": 0.8,
        } for i in range(5)
    ]
    wrapped = create_research_report.run(
        research_result={"providers": ["arxiv"], "arxiv": {"papers": papers, "relevance_gate": {"threshold": 0.18}}},
        output_path="agent_memory_research.md", question="find the latest 5 papers about long-term memory for AI agents",
    )
    assert wrapped.ok is True
    assert wrapped.data["verified"] is True

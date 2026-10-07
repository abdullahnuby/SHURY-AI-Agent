from types import SimpleNamespace


def test_paper_focused_research_prefers_official_arxiv_and_isolates_web_failure(monkeypatch):
    from app.knowledge.web_research import WebResearchEngine

    class FakeGateway:
        def arxiv_search(self, query, limit=8):
            return [
                {"rank": 1, "title": "Memory paper", "url": "https://arxiv.org/abs/1234.5678",
                 "abstract": "temporal episodic memory with hybrid retrieval", "published": "2026-01-01T00:00:00+00:00",
                 "updated": "2026-01-01T00:00:00+00:00", "authors": ["A"], "source": "arxiv"}
            ]
        def search_web(self, query, limit=5):
            raise AssertionError("paper-focused research must not scrape a search engine")
        def github_search_repositories(self, query, limit=8):
            raise AssertionError("paper-focused research must not require GitHub")

    class FakeRag:
        def index_knowledge_text(self, *args, **kwargs):
            return {"ok": True}

    engine = WebResearchEngine(gateway=FakeGateway(), rag=FakeRag())
    result = engine.internet_research("find the latest 5 papers on long-term memory for AI agents", paper_limit=5)
    assert result["providers"] == ["arxiv"]
    assert len(result["arxiv"]["papers"]) == 1
    assert result["provider_errors"] == []


def test_non_paper_research_degrades_when_web_provider_is_blocked(monkeypatch):
    from app.knowledge.web_research import WebResearchEngine

    class FakeGateway:
        def search_web(self, query, limit=5):
            raise PermissionError("robots.txt disallows this URL")
        def arxiv_search(self, query, limit=8):
            return []
        def github_search_repositories(self, query, limit=8):
            return []

    engine = WebResearchEngine(gateway=FakeGateway(), rag=SimpleNamespace())
    result = engine.internet_research("current industry information", providers=("web", "arxiv", "github"), index=False)
    assert result["web"]["sources"] == []
    assert result["provider_errors"]
    assert result["provider_errors"][0]["provider"] == "web"

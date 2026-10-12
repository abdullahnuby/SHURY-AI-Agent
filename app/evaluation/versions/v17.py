from __future__ import annotations
from pathlib import Path
import json
import tempfile
from app.integrations.network import NetworkGateway, FetchResult, extract_text, validate_public_url
from app.knowledge.web_research import WebResearchEngine
from app.integrations.devops import inspect_project, check_project
from app.knowledge.rag import RAGEngine


class _FakeGateway(NetworkGateway):
    def __init__(self, root: Path):
        super().__init__(db_path=root / "network.db", cache_dir=root / "cache", rate_limit_seconds=0.0)
        self.pages = {
            "https://example.org/a": ("Example A", "text/html; charset=utf-8", b"<html><h1>Algorithm A</h1><p>deterministic retrieval evidence and data analysis.</p></html>"),
            "https://example.org/b": ("Example B", "text/html; charset=utf-8", b"<html><h1>Algorithm B</h1><p>agentic retrieval uses evidence and adaptive data analysis.</p></html>"),
        }

    def search_web(self, query: str, limit: int = 5):
        rows = []
        for i, (url, (title, _, body)) in enumerate(self.pages.items(), 1):
            rows.append({"rank": i, "title": title, "url": url, "snippet": extract_text(body, "text/html"), "source": "fake"})
        return rows[:limit]

    def arxiv_search(self, query: str, limit: int = 8):
        return [{"rank": 1, "title": "Adaptive Retrieval Algorithms", "url": "https://arxiv.org/abs/1701.00001",
                 "abstract": "adaptive retrieval evidence algorithm benchmark", "published": "2026-09-01T00:00:00Z",
                 "updated": "2026-09-02T00:00:00Z", "authors": ["Researcher"], "source": "arxiv"}][:limit]

    def github_search_repositories(self, query: str, limit: int = 8):
        return [{"rank": 1, "full_name": "example/research-agent", "html_url": "https://github.com/example/research-agent",
                 "description": "agentic research and retrieval", "language": "Python", "stars": 42,
                 "updated_at": "2026-09-10T00:00:00Z", "default_branch": "main"}][:limit]

    def fetch(self, url: str, **kwargs):
        title, ctype, body = self.pages[url]
        return FetchResult(url, url, 200, ctype, body, __import__("hashlib").sha256(body).hexdigest(), 1.0, False, True)


def run_v17_benchmark():
    cases=[]
    with tempfile.TemporaryDirectory(prefix="agent-v17-bench-") as td:
        root=Path(td)
        corpus=root/"corpus"; corpus.mkdir()
        (corpus/"guide.md").write_text("# Retrieval\n\nAdaptive retrieval should stop when evidence is sufficient.\n", encoding="utf-8")
        (corpus/"facts.csv").write_text("id,value\n1,10\n2,20\n", encoding="utf-8")
        gateway=_FakeGateway(root)
        rag=RAGEngine(root/"rag.db")
        research=WebResearchEngine(gateway, rag)

        cases.append(("url_public_validation", validate_public_url("https://93.184.216.34") == "https://93.184.216.34/"))
        blocked=False
        try:
            validate_public_url("http://127.0.0.1:8080/")
        except ValueError:
            blocked=True
        cases.append(("ssrf_private_block", blocked))

        res=research.research("agentic retrieval data analysis", limit=2, index=True)
        cases.append(("web_research", res["count"] == 2 and all(x.get("indexed") for x in res["sources"])))
        q=rag.query("adaptive retrieval evidence")
        cases.append(("web_to_rag", q["grounded"] and any("example.org" in e["source"] for e in q["evidence"])))
        text=extract_text(b"<html><script>x</script><h1>Title</h1><p>Hello world</p></html>", "text/html")
        cases.append(("html_extraction", "Title" in text and "Hello world" in text and "x" not in text))
        papers=research.arxiv_research("retrieval algorithms", limit=1, index=True)
        cases.append(("arxiv_research", papers["count"] == 1 and papers["indexed"] == 1))
        combined=research.internet_research("RAG algorithms data agents", web_limit=1, paper_limit=1, repo_limit=1, index=True)
        cases.append(("combined_research", combined["policy"].startswith("web + arXiv + GitHub") and combined["indexed_items"] >= 2))
        repos=research.github_search("agentic research", limit=1)
        cases.append(("github_discovery", repos["count"] == 1 and repos["repositories"][0]["full_name"] == "example/research-agent"))

        info=inspect_project(Path(__file__).resolve().parents[3])
        cases.append(("project_inspection", "python" in info["stack"] and any(c["name"] == "compile" for c in info["commands"])))
        checked=check_project(Path(__file__).resolve().parents[3], ("compile",))
        cases.append(("project_compile_check", checked["all_passed"]))

    passed=sum(ok for _,ok in cases)
    return {"passed":passed,"total":len(cases),"cases":[{"name":n,"passed":bool(ok)} for n,ok in cases]}

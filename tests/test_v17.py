from pathlib import Path
from app.integrations.network import validate_public_url, extract_text
from app.knowledge.web_research import WebResearchEngine
from app.knowledge.rag import RAGEngine
from app.integrations.devops import inspect_project, check_project
from app.evaluation.versions.v17 import run_v17_benchmark, _FakeGateway


def test_v17_blocks_private_networks():
    for url in ("http://127.0.0.1/", "http://10.0.0.1/", "http://192.168.1.1/", "http://[::1]/"):
        try:
            validate_public_url(url)
            assert False, url
        except ValueError:
            pass


def test_v17_public_url_normalization():
    assert validate_public_url("HTTPS://93.184.216.34/path?q=1#fragment") == "https://93.184.216.34/path?q=1"


def test_v17_html_extraction():
    text=extract_text(b"<html><script>alert(1)</script><h1>A</h1><p>B text</p></html>", "text/html")
    assert "A" in text and "B text" in text and "alert" not in text


def test_v17_web_research_indexes_into_rag(tmp_path):
    rag=RAGEngine(tmp_path/"rag.db")
    out=WebResearchEngine(_FakeGateway(tmp_path), rag).research("adaptive retrieval data analysis", limit=2, index=True)
    assert out["count"] == 2
    assert all(x.get("indexed") for x in out["sources"])
    hit=rag.query("adaptive retrieval evidence")
    assert hit["grounded"]


def test_v17_project_inspection_and_compile():
    root=Path(__file__).resolve().parents[1]
    info=inspect_project(root)
    assert "python" in info["stack"]
    out=check_project(root, ("compile",))
    assert out["all_passed"]
    from app.runtime.registry import load_tools
    assert load_tools()["check_project"].requires_approval is True


def test_v17_benchmark_green():
    out=run_v17_benchmark()
    assert out["passed"] == out["total"] == 10


def test_v17_online_intent_routes_away_from_notes_and_local_rag():
    from app.planning.planner import RulePlanner
    cases = {
        "search the internet for latest RAG research": "web_research",
        "بحث على الانترنت عن أحدث أبحاث RAG": "web_research",
        "أحدث أبحاث RAG": "arxiv_research",
        "rag what requires approval": "rag_query",
        "search notes deployment": "search_notes",
    }
    for goal, expected in cases.items():
        plan = RulePlanner().plan(goal)
        assert plan.steps and plan.steps[0].tool == expected


def test_v17_compound_online_research_routes_to_combined_engine():
    from app.planning.planner import RulePlanner
    goal = "Search For The Newest Research For RAG and Algorithms and Data Analysis And Agents in Web and Github"
    plan = RulePlanner().plan(goal)
    assert plan.steps and plan.steps[0].tool == "internet_research"
    assert len(plan.steps[0].args["query"]) > 40

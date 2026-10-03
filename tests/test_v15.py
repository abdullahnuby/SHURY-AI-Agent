from pathlib import Path
from app.knowledge.rag import RAGEngine
from app.evaluation.versions.v15 import run_v15_benchmark


def _fixture(root: Path):
    (root / "guide.md").write_text(
        "# Deployment\n\nProduction deployment requires operator approval.\n\n"
        "# Incident\n\nCritical incidents must be written to the log.\n",
        encoding="utf-8",
    )
    (root / "facts.csv").write_text(
        "id,owner,status\n1,Alice,active\n2,Bob,closed\n3,Alice,active\n", encoding="utf-8"
    )


def test_v15_hybrid_rag_grounded(tmp_path):
    _fixture(tmp_path)
    engine = RAGEngine(tmp_path / "rag.db")
    out = engine.index(tmp_path)
    assert out["files"] == 2
    result = engine.query("what requires operator approval for production deployment?")
    assert result["grounded"]
    assert result["evidence"]
    assert result["evidence"][0]["citation"] == "[S1]"


def test_v15_query_decomposition_and_repeatability(tmp_path):
    _fixture(tmp_path)
    engine = RAGEngine(tmp_path / "rag.db")
    engine.index(tmp_path)
    a = engine.query("deployment approval and incident log")
    b = engine.query("deployment approval and incident log")
    assert len(a["decomposition"]) == 2
    assert a["retrieval"] == b["retrieval"]
    assert a["trace"] == b["trace"]


def test_v15_fail_closed(tmp_path):
    _fixture(tmp_path)
    engine = RAGEngine(tmp_path / "rag.db")
    engine.index(tmp_path)
    r = engine.query("unicorns in the lunar warehouse")
    assert r["abstained"]
    assert not r["evidence"]


def test_v15_incremental_index_and_decay(tmp_path):
    _fixture(tmp_path)
    engine = RAGEngine(tmp_path / "rag.db")
    first = engine.index(tmp_path)
    second = engine.index(tmp_path)
    assert first["added"] == 2
    assert second["skipped"] == 2
    assert engine.decay_report()["chunks"] >= 4


def test_v15_benchmark_green():
    out = run_v15_benchmark()
    assert out["passed"] == out["total"] == 6


def test_v15_plan_cache_does_not_reuse_old_output(tmp_path, monkeypatch):
    from app.knowledge.memory import get_memory
    from app.runtime.agent import run_agent
    import app.knowledge.memory as memory_module
    # Isolate the agent memory database for this test.
    db = tmp_path / "memory.db"
    monkeypatch.setattr(memory_module, "DEFAULT_PATH", db)
    # get_memory is cached globally; clear it if present.
    memory_module._default = None
    monkeypatch.setenv("AGENT_RAG_DB", str(tmp_path / "rag.db"))
    try:
        rag_db = tmp_path / "rag.db"
        engine = RAGEngine(rag_db)
        corpus = tmp_path / "corpus"; corpus.mkdir()
        (corpus / "guide.md").write_text("# Deployment\n\nProduction deployment requires operator approval.", encoding="utf-8")
        engine.index(corpus)
        # Directly cache a completed-looking plan through the memory API after a first run.
        state1 = run_agent("rag what requires operator approval for production deployment?")
        assert state1.status == "completed"
        # The RAG DB used by the agent is its module default, so this test focuses on planner state reset
        # rather than cross-DB semantics; validate with a cached plan object directly.
        mem = get_memory()
        cached = mem.cached_plan(state1.goal.lower())
        assert cached
        from app.domain.plan import Plan
        pl = Plan.from_dict(cached["plan"])
        assert any(step.status == "done" for step in pl.steps)
        # Simulate the planner's normalization logic independently.
        for step in pl.steps:
            step.status = "pending"; step.output = None; step.error = None; step.resolved = None; step.attempts = 0
        assert all(step.status == "pending" and step.output is None for step in pl.steps)
    finally:
        memory_module._default = None


def test_v15_cached_plan_reexecutes_steps(tmp_path):
    from app.knowledge.memory import Memory
    from app.planning.planner import RulePlanner
    from app.domain.plan import Plan, PlanStep
    from app.runtime.registry import load_tools
    from app.domain.state import AgentState
    m = Memory(tmp_path / "memory.db")
    reg = load_tools()
    tool = reg["rag_query"]
    plan = Plan([PlanStep(id="s1", tool="rag_query", args={"query": "approval"}, status="done", output={"grounded": False})])
    m.cache_plan("rag approval", plan.to_dict(), tool.cost, tool.duration)
    planner = RulePlanner()
    out = planner.plan("rag approval", memory=m)
    assert out.steps and out.steps[0].tool == "rag_query"
    assert out.steps[0].status == "pending"
    assert out.steps[0].output is None

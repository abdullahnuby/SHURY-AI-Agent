import app.knowledge.memory as memory
import app.runtime.agent as agent_mod
from app.domain.plan import Plan, PlanStep
from app.domain.world import WorldState
from app.intelligence.cognitive.controller import CognitiveController
from app.runtime.cognitive_agent import run_cognitive
from app.runtime.registry import load_tools


def setup(tmp_path):
    memory.configure(tmp_path / "m.db")
    agent_mod.LOG_FILE = tmp_path / "a.jsonl"
    (tmp_path / "ws").mkdir()
    return tmp_path


def test_cognitive_analysis_uses_baseline_as_candidate(tmp_path):
    setup(tmp_path)
    baseline = Plan([PlanStep("s1", "calculator", {"expression": "4*6"})], planner="v10-portfolio")
    c = CognitiveController()
    b = c.analyze("calculate 4*6", memory.get_memory(), WorldState(), load_tools(), baseline_plan=baseline)
    assert b.baseline_plan[0]["tool"] == "calculator"
    assert b.mode == "deterministic"


def test_cognitive_reflection_detects_failure_and_requests_replan(tmp_path):
    setup(tmp_path)
    c = CognitiveController()
    c.analyze("calculate 4*6", memory.get_memory(), WorldState(), load_tools())
    r = c.reflect({"id": "s1", "tool": "calculator"}, {"tool": "calculator", "ok": False, "error": "bad input"}, [])
    assert r.goal_status == "blocked" and r.should_replan
    assert r.mode == "deterministic"


def test_cognitive_agent_uses_retrieval_native_semantics(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    s = run_cognitive("calculate 4*6", max_steps=2)
    assert s.status == "completed"
    assert [x.tool for x in s.plan.steps] == ["calculator"]
    assert s.plan.diagnostics["semantic_engine"] == "arabic-retrieval-v1.0"
    assert s.plan.diagnostics["canonical_brain"] is True
    assert "llm" not in str(s.plan.diagnostics).casefold()


def test_cognitive_clarifies_without_executing(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    s = run_cognitive("حلل الملف", max_steps=2)
    assert s.status == "needs_user" and s.final_message and not s.plan.steps

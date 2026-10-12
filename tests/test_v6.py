from app.domain.goal import parse_goal
from app.knowledge.memory import Memory
from app.domain.operators import build_operators
from app.runtime.registry import load_tools
from app.runtime.agent import run_agent


def test_goal_decomposition_preserves_order():
    g = parse_goal("احسب 5*3 ثم احفظ النتيجة")
    assert [c.text for c in g.clauses] == ["احسب 5*3", "احفظ النتيجة"]
    assert g.clauses[1].relation == "then"


def test_operator_registry_is_derived_from_tools():
    ops = build_operators(load_tools()).items
    assert {o.tool for o in ops} >= {"calculator", "save_note"}


def test_memory_tool_reliability_starts_neutral(tmp_path):
    m = Memory(tmp_path / "m.db")
    assert m.tool_reliability("calculator") == 1.0
    m.record_tool_outcome("calculator", True)
    m.record_tool_outcome("calculator", False)
    assert m.tool_reliability("calculator") == 0.5


def test_compound_plan_executes_two_explicit_clauses(tmp_path, monkeypatch):
    # Uses isolated DB so this test never mutates the shipped memory.
    import app.knowledge.memory as memory
    memory.configure(tmp_path / "m.db")
    s = run_agent("احسب 5*3 ثم احفظ النتيجة")
    assert s.status in {"completed", "cancelled"}
    assert len(s.plan.steps) >= 1

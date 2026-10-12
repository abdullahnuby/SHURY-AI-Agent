from app.intelligence.understanding import understand
from app.planning.decision import decide
from app.domain.context import resolve_goal
from app.domain.world import WorldState
from app.domain.task_graph import TaskGraph, TaskNode
from app.runtime.registry import load_tools
from app.runtime.agent import run_agent


def test_task_graph_dependencies():
    g = TaskGraph([TaskNode("a", "calculator", {}), TaskNode("b", "save_note", {}, ["a"])])
    assert g.validate() == []
    assert [n.id for n in g.ready()] == ["a"]
    g.nodes[0].status = "done"
    assert [n.id for n in g.ready()] == ["b"]


def test_task_graph_rejects_cycles_and_self_dependencies():
    cycle = TaskGraph([
        TaskNode("a", "calculator", {}, ["b"]),
        TaskNode("b", "save_note", {}, ["a"]),
    ])
    cycle_errors = cycle.validate()
    assert any("cycle:" in e for e in cycle_errors)

    self_loop = TaskGraph([TaskNode("a", "calculator", {}, ["a"])])
    assert any("self_dependency:a" in e for e in self_loop.validate())


def test_task_graph_validates_dependencies_independent_of_order():
    graph = TaskGraph([
        TaskNode("step-2", "analyze_dataset", {}, ["step-1"]),
        TaskNode("step-1", "profile_dataset", {}),
    ])
    assert graph.validate() == []

    missing = TaskGraph([
        TaskNode("step-2", "analyze_dataset", {}, ["missing-step"]),
        TaskNode("step-1", "profile_dataset", {}),
    ])
    assert any("missing_dependency:step-2->missing-step" in e for e in missing.validate())


def test_context_requires_evidence():
    g = WorldState(last_goal="احسب 5*3", last_outputs={"last_result": 15})
    assert resolve_goal("استخدم النتيجة", g)[0] == "استخدم 15"
    assert resolve_goal("استخدم النتيجة", WorldState())[1] is True


def test_dataset_follow_up_reuses_only_explicit_completed_target():
    world = WorldState(last_goal="analyze sales.csv for anomalies")
    assert resolve_goal("focus on Q3", world) == ("analyze sales.csv for anomalies ; focus on Q3", False)
    assert resolve_goal("ركز على الربع الثالث", world) == (
        "analyze sales.csv for anomalies ; ركز على الربع الثالث",
        False,
    )
    assert resolve_goal("focus on Q3", WorldState()) == ("focus on Q3", False)

    second_goal = resolve_goal("focus on Q3", world)[0]
    third_goal = resolve_goal("compare it to last year", WorldState(last_goal=second_goal))[0]
    assert "sales.csv" in third_goal
    assert "focus on Q3" in third_goal
    assert "compare it to last year" in third_goal


def test_colloquial_social_turn_is_not_misclassified_as_ambiguous():
    u = understand("احسب وسجل 12")
    plan = run_agent("ايه الأخبار")
    assert plan.status == "completed"
    assert plan.final_message == "أنا شغال كويس 😄 وإنت عامل إيه؟"


def test_decision_has_conservative_threshold():
    class X: pass
    u = X(); u.top_intent = None; u.ambiguous = False
    class P: steps=[]
    assert decide(u, P(), load_tools()).action == "clarify"

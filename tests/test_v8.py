import threading
import time
from pathlib import Path

import app.knowledge.memory as memory
import app.runtime.agent as agent_mod
from app.runtime.agent import run_agent, plan_only, reliability_report
from app.domain.goal import parse_goal
from app.runtime.registry import Tool, register, REGISTRY
from app.domain.plan import Plan, PlanStep
from app.planning.planner import RulePlanner
from app.runtime.registry import load_tools


def test_planner_can_insert_missing_precondition_producer(tmp_path):
    memory.configure(tmp_path / "m.db")

    # This is a support operator and should not directly match the user goal.
    register(Tool("prepare_v8", "prepare resource", {}, lambda: "ready",
         match=lambda g: False, capability="prepare", produces=("prepared",),
         cost=0.5, risk="low"))
    register(Tool("needs_prepare_v8", "use prepared resource", {}, lambda: "done",
                  triggers=("needpreparev8",), capability="use_prepared",
                  preconditions=("prepared",), produces=("goal_done",), cost=1.0, risk="low"))
    try:
        plan, errors = plan_only("needpreparev8")
        assert not errors
        assert [s.tool for s in plan.steps] == ["prepare_v8", "needs_prepare_v8"]
        assert plan.steps[1].depends_on == ["s1"]
    finally:
        REGISTRY.pop("prepare_v8", None)
        REGISTRY.pop("needs_prepare_v8", None)


def test_parallel_ready_steps_are_executed_concurrently(tmp_path):
    memory.configure(tmp_path / "m.db")
    barrier = threading.Barrier(2, timeout=2)
    entered = []

    def parallel_tool():
        entered.append(time.monotonic())
        barrier.wait()
        return "ok"

    register(Tool("parallel_v8", "parallel", {}, parallel_tool, triggers=("parallelv8",),
                  capability="parallel", produces=("parallel_done",), parallel_safe=True,
                  idempotent=True, cost=1.0))
    try:
        state = run_agent("parallelv8 و parallelv8")
        assert state.status == "completed"
        assert len(entered) == 2
        assert all(s.status == "done" for s in state.plan.steps)
    finally:
        REGISTRY.pop("parallel_v8", None)


def test_explicit_cost_constraint_uses_real_path_cost(tmp_path):
    memory.configure(tmp_path / "m.db")
    plan, errors = plan_only("احسب 2+2 بميزانية 1")
    assert not errors and plan.steps
    assert plan.estimated_cost <= 1.0


def test_experience_cache_reuses_verified_plan(tmp_path):
    memory.configure(tmp_path / "m.db")
    first = run_agent("احسب 8*8")
    assert first.status == "completed"
    cached = memory.get_memory().cached_plan("احسب 8*8")
    assert cached and cached["success_count"] >= 1
    second = run_agent("احسب 8*8")
    assert second.status == "completed"
    assert second.plan.planner == "v8-experience-reuse"


def test_ranked_memory_does_not_return_non_matches(tmp_path):
    m = memory.Memory(tmp_path / "m.db")
    m.add_note("اجتماع احمد بخصوص المشروع", importance=5)
    m.add_note("موعد تسليم التقرير")
    assert m.search_notes("احمد") == ["اجتماع احمد بخصوص المشروع"]
    assert m.search_notes("غير موجود") == []


def test_checkpoint_integrity_is_verified(tmp_path):
    m = memory.Memory(tmp_path / "m.db")
    p = Plan([PlanStep("s1", "get_time", {})])
    m.start_run("r1", "t1", "hello", p.to_dict())
    m.checkpoint("r1", "hello", p.to_dict(), {}, {}, 0, "running")
    loaded = m.load_checkpoint("r1")
    assert loaded and loaded["revision"] == 1
    # Tamper directly with durable bytes; integrity must fail closed.
    conn = m._connect()
    try:
        with conn:
            conn.execute("UPDATE checkpoints SET outputs=? WHERE run_id=?", ('{"tampered":true}', "r1"))
    finally:
        conn.close()
    try:
        m.load_checkpoint("r1")
        assert False, "tampered checkpoint should fail"
    except ValueError as e:
        assert "integrity" in str(e)


def test_effects_capture_state_transition_hashes(tmp_path):
    memory.configure(tmp_path / "m.db")
    agent_mod.LOG_FILE = tmp_path / "agent.jsonl"
    state = run_agent("احسب 3*3")
    effects = memory.get_memory().effects(state.run_id)
    assert effects and effects[0]["state_before"] and effects[0]["state_after"]
    assert effects[0]["state_before"] != effects[0]["state_after"]


def test_reliability_report_has_horizon_dimension(tmp_path):
    memory.configure(tmp_path / "m.db")
    run_agent("احسب 2+3")
    run_agent("احسب 4+5")
    report = reliability_report()
    assert report["runtime_runs"] >= 2
    assert report["horizon_survival"].get(1) == 1.0
    assert "calculator" in report["tool_metrics"]


def test_run_still_supports_custom_planner_signature(tmp_path):
    memory.configure(tmp_path / "m.db")
    class Fixed:
        def plan(self, goal, memory=None):
            return Plan([PlanStep("s1", "get_time", {})])
    state = run_agent("custom-v8", planner=Fixed())
    assert state.status == "completed"


def test_resume_recovers_verified_effect_without_rerunning_non_idempotent_tool(tmp_path):
    m = memory.Memory(tmp_path / "m.db")
    calls = {"n": 0}

    def side_effect():
        calls["n"] += 1
        return "already-done"

    register(Tool("crash_side_effect_v8", "crash side effect", {}, side_effect,
                  triggers=("crashv8",), capability="crash_side_effect",
                  produces=("side_effect_done",), idempotent=False, cost=1.0))
    try:
        plan = Plan([PlanStep("s1", "crash_side_effect_v8", {}, clause_text="crashv8")])
        m.start_run("crash-run", "trace", "crashv8", plan.to_dict())
        m.checkpoint("crash-run", "crashv8", plan.to_dict(), {}, {}, 0, "running")
        before = "before-hash"
        after = "after-hash"
        m.record_effect(run_id="crash-run", step_id="s1", attempt=1,
                        tool="crash_side_effect_v8", args={}, output="already-done",
                        ok=True, verified=True, error=None, duration_ms=2.0,
                        state_before=before, state_after=after)
        # Resume must consume the durable effect and never execute the function again.
        memory.configure(tmp_path / "m.db")
        import app.runtime.agent as agent_mod_local
        resumed = agent_mod_local.resume_agent("crash-run")
        assert resumed.status == "completed"
        assert calls["n"] == 0
        assert resumed.plan.steps[0].output == "already-done"
    finally:
        REGISTRY.pop("crash_side_effect_v8", None)


def test_recall_context_separates_semantic_episodic_and_procedural_memory(tmp_path):
    m = memory.Memory(tmp_path / "m.db")
    m.set_fact("اسم المشروع", "نخيل")
    m.add_note("قرار المشروع: نستخدم SQLite", importance=5)
    p = Plan([PlanStep("s1", "get_time", {})])
    m.cache_plan("الساعة كام", p.to_dict(), 1.0, 0.01)
    m.record_run("الساعة كام", "completed", p.to_dict(), "done")
    ctx = m.recall_context("المشروع")
    assert "semantic" in ctx and "episodic" in ctx and "procedural" in ctx
    assert ctx["semantic"]
    assert any("المشروع" in x["goal"] for x in ctx["episodic"]) is False
    assert ctx["procedural"] == []

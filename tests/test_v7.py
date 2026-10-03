import tempfile
from pathlib import Path

import app.knowledge.memory as memory
import app.runtime.agent as agent_mod
from app.runtime.registry import Tool, register, REGISTRY
from app.domain.plan import Plan, PlanStep
from app.planning.planner import RulePlanner
from app.runtime.agent import run_agent, resume_agent, replay_run
from app.evaluation.benchmarks import run_memory_benchmark


def test_search_planner_prefers_low_cost_candidate(tmp_path):
    memory.configure(tmp_path / "m.db")
    calls = []

    def cheap():
        calls.append("cheap")
        return "cheap-ok"

    def expensive():
        calls.append("expensive")
        return "expensive-ok"

    register(Tool("cheap_cap", "cheap recovery", {}, cheap, triggers=("choosev7",),
                  capability="choose", produces=("chosen",), cost=1.0, parallel_safe=True))
    register(Tool("expensive_cap", "expensive recovery", {}, expensive, triggers=("choosev7",),
                  capability="choose", produces=("chosen",), cost=5.0, parallel_safe=True))
    try:
        plan = RulePlanner().plan("choosev7", memory.get_memory())
        assert [s.tool for s in plan.steps] == ["cheap_cap"]
        run_agent("choosev7")
        assert calls == ["cheap"]
    finally:
        REGISTRY.pop("cheap_cap", None)
        REGISTRY.pop("expensive_cap", None)


def test_replan_uses_alternative_after_failure(tmp_path):
    memory.configure(tmp_path / "m.db")
    calls = []

    def primary():
        calls.append("primary")
        raise RuntimeError("primary-down")

    def fallback():
        calls.append("fallback")
        return "recovered"

    register(Tool("primary_v7", "primary", {}, primary, triggers=("recoveryv7",),
                  capability="recovery", produces=("recovered",), cost=1.0, retries=0))
    register(Tool("fallback_v7", "fallback", {}, fallback, triggers=("recoveryv7",),
                  capability="recovery", produces=("recovered",), cost=2.0, retries=0))
    try:
        state = run_agent("recoveryv7", max_replans=2)
        assert state.status == "completed"
        assert state.replans == 1
        assert state.plan.steps[0].tool == "fallback_v7"
        assert calls == ["primary", "fallback"]
    finally:
        REGISTRY.pop("primary_v7", None)
        REGISTRY.pop("fallback_v7", None)


def test_effect_ledger_and_replay_are_non_executing(tmp_path):
    memory.configure(tmp_path / "m.db")
    state = run_agent("احسب 9*9")
    effects = replay_run(state.run_id)
    assert state.status == "completed"
    assert len(effects) == 1
    assert effects[0]["tool"] == "calculator"
    assert effects[0]["ok"] is True
    assert effects[0]["verified"] is True
    # A second replay reads the ledger; it must not create another effect.
    assert len(replay_run(state.run_id)) == 1


def test_resume_uses_checkpointed_plan_not_new_planner(tmp_path):
    memory.configure(tmp_path / "m.db")
    agent_mod.LOG_FILE = tmp_path / "agent.jsonl"

    class Fixed:
        def plan(self, goal, memory=None):
            return Plan([PlanStep("s1", "get_time", {}), PlanStep("s2", "get_time", {})])

    state = run_agent("resume-v7", planner=Fixed(), max_steps=1)
    assert state.status == "max_steps"
    assert state.plan.steps[1].status == "skipped"

    resumed = resume_agent(state.run_id, max_steps=6)
    assert resumed.status == "completed"
    assert resumed.plan.steps[0].output is not None
    assert resumed.plan.steps[1].output is not None


def test_selective_forgetting_and_cross_session(tmp_path):
    path = tmp_path / "m.db"
    result = run_memory_benchmark(path)
    assert result["accuracy"] == 1.0


def test_v7_plan_manifest_contains_contracts(tmp_path):
    memory.configure(tmp_path / "m.db")
    plan = RulePlanner().plan("احسب 7*8", memory.get_memory())
    assert plan.steps[0].capability == "calculate"
    manifest = {t["name"]: t for t in __import__("app.runtime.registry", fromlist=["manifest"]).manifest()}
    assert manifest["calculator"]["capability"] == "calculate"
    assert "produces" in manifest["calculator"]

from __future__ import annotations

from pathlib import Path

from app.domain.world import WorldState, StateDelta
from app.knowledge.memory import Memory
from app.runtime.registry import Tool
from app.tools.system.world import simulate_action_tool
from app.world.model import WorldModel
from app.world.store import load_session_world, save_session_world


def test_prediction_tracks_capabilities_not_facts():
    tool = Tool(name="demo", description="demo", params={}, fn=lambda: None, produces=("ready",), removes=("stale",))
    p = WorldModel().predict(tool, {}, WorldState())
    assert p.expected_changes.added_capabilities == ("ready",)
    assert p.expected_changes.removed_capabilities == ("stale",)


def test_observation_records_actual_state_diff():
    before = WorldState(capabilities={"stale"})
    after = WorldState.from_snapshot(before.snapshot())
    after.transition(StateDelta(add=("ready",), remove=("stale",)), op="demo")
    obs = WorldModel().observe(world_before=before, world_after=after,
                               tool="demo", ok=True, verified=True, output={"ok": True})
    assert obs.state_diff.added_capabilities == ("ready",)
    assert obs.state_diff.removed_capabilities == ("stale",)
    assert obs.confidence == 1.0
    assert after.observations[-1]["observation_id"] == obs.observation_id


def test_prediction_comparison_is_exact_when_contract_matches():
    tool = Tool(name="demo", description="demo", params={}, fn=lambda: None, produces=("ready",))
    wm = WorldModel()
    before = WorldState()
    pred = wm.predict(tool, {}, before)
    after = WorldState.from_snapshot(before.snapshot())
    after.transition(StateDelta(add=("ready",)), op="demo")
    obs = wm.observe(world_before=before, world_after=after, tool="demo", ok=True, verified=True)
    assert wm.compare_prediction(pred, obs.state_diff)["exact"] is True


def test_structured_world_delta_is_strict():
    wm = WorldModel()
    world = WorldState()
    diff = wm.apply_structured_observation(world, {"world_delta": {
        "add_facts": ["deployed"],
        "variables": {"build": "green"},
        "entities": {"repo": {"kind": "repository", "attributes": {"branch": "main"}}},
        "relations": [{"subject": "repo", "predicate": "has_branch", "object": "main"}],
    }})
    assert world.facts["deployed"] == "true"
    assert world.variables["build"] == "green"
    assert "repo" in world.entities
    assert world.relations
    assert diff.added_facts == ("deployed",)


def test_session_world_persists_and_is_isolated(tmp_path):
    mem = Memory(Path(tmp_path) / "memory.db")
    save_session_world(mem, "a", WorldState(facts={"city": "Luxor"}))
    assert load_session_world(mem, "a").facts["city"] == "Luxor"
    assert load_session_world(mem, "b").facts.get("city") is None


def test_simulate_action_is_read_only(tmp_path, monkeypatch):
    mem = Memory(Path(tmp_path) / "memory.db")
    import app.knowledge.memory as memory_module
    memory_module._MEMORY = mem
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path / "workspace"))
    out = simulate_action_tool.fn("calculator", {"expression": "2+2"})
    assert out["source"] == "deterministic-contract"
    assert out["action"] == "calculator"
    assert "expected_changes" in out


def test_structured_world_delta_is_not_applied_by_default(tmp_path):
    from app.runtime.registry import Tool, ToolResult
    from app.runtime.agent import _apply_success
    import app.knowledge.memory as memory_mod

    world = WorldState()
    state = type("S", (), {})()
    state.world = world
    state.outputs = {}
    state.trace_id = "t"
    state.run_id = "r"
    tool = Tool(name="untrusted", description="x", params={}, fn=lambda: None)
    step = type("Step", (), {"id": "s1", "tool": "untrusted", "args": {}, "status": "pending", "output": None, "error": None})()
    mem = memory_mod.Memory(tmp_path / "world-delta.db")
    effect_id = mem.record_effect(
        run_id="r", step_id="s1", attempt=1, tool="untrusted", args={}, output={},
        ok=True, verified=True, error=None, duration_ms=0.0, state_before=world.fingerprint()
    )
    _apply_success(state, step, tool, ToolResult(ok=True, data={"world_delta": {"add_facts": ["secret=true"]}}), 0.0, effect_id, mem, False)
    assert "secret=true" not in state.world.facts


def test_world_model_context_omits_raw_observation_payload():
    wm = WorldModel()
    world = WorldState()
    obs = wm.observe(world_before=WorldState(), world_after=world, tool="read_file", ok=True, verified=True,
                      output={"secret": "do-not-copy"})
    ctx = wm.context(world, limit=5)
    assert ctx["recent_observations"]
    public = ctx["recent_observations"][0]
    assert "raw_output" not in public
    assert "summary" not in public


def test_world_model_prediction_is_deterministic_and_learned_only():
    tool = Tool(name="demo", description="demo", params={}, fn=lambda: 1, produces=("done",))
    wm = WorldModel()
    prediction = wm.predict(tool, {}, WorldState())
    assert prediction.source in {"deterministic-contract", "learned-transition-model"}
    assert prediction.action == "demo"

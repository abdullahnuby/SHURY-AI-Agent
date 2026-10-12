from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path

from app.domain.world import WorldState, StateDelta
from app.knowledge.memory import Memory
from app.runtime.registry import Tool
from app.world.model import WorldModel
from app.world.store import load_session_world, save_session_world


def run_world_model_benchmark() -> dict:
    cases = []
    wm = WorldModel()

    # Contract prediction should describe the same state dimension the runtime mutates.
    tool = Tool(name="demo", description="demo", params={}, fn=lambda: {"ok": True}, produces=("ready",), removes=("stale",))
    world = WorldState(facts={"stale": "true"})
    prediction = wm.predict(tool, {}, world)
    cases.append((
        "contract prediction uses capabilities",
        prediction.expected_changes.added_capabilities == ("ready",)
        and prediction.expected_changes.removed_capabilities == ("stale",)
    ))

    before = WorldState(capabilities={"stale"}, facts={"stale_fact": "1"})
    after = WorldState.from_snapshot(before.snapshot())
    after.transition(StateDelta(add=("ready",), remove=("stale",)), op="demo")
    obs = wm.observe(world_before=before, world_after=after, tool="demo", ok=True, verified=True, output={"x": 1})
    cases.append((
        "observation diff",
        obs.state_diff.added_capabilities == ("ready",)
        and obs.state_diff.removed_capabilities == ("stale",)
        and obs.confidence == 1.0
    ))

    comparison = wm.compare_prediction(prediction, obs.state_diff)
    cases.append(("prediction matches actual", comparison["exact"] is True))

    unsafe = WorldState(resources={"budget": -1})
    assessment = wm.assess(unsafe)
    cases.append(("state invariant detects negative resource", assessment.consistent is False and "resource_negative" in assessment.risks))

    with TemporaryDirectory() as td:
        mem = Memory(Path(td) / "memory.db")
        sid_a, sid_b = "a", "b"
        wa = WorldState(facts={"city": "Luxor"})
        save_session_world(mem, sid_a, wa)
        cases.append(("session world persists", load_session_world(mem, sid_a).facts.get("city") == "Luxor"))
        cases.append(("session isolation", load_session_world(mem, sid_b).facts.get("city") is None))

    return {
        "passed": sum(bool(ok) for _, ok in cases),
        "total": len(cases),
        "accuracy": sum(bool(ok) for _, ok in cases) / max(1, len(cases)),
        "cases": [{"name": name, "passed": bool(ok)} for name, ok in cases],
    }

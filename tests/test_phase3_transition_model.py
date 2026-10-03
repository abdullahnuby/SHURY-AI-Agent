from __future__ import annotations

from app.brain.models import ActionSpec
from app.learning.store import LearningStore
from app.learning.transition_model import LearnedTransitionModel, action_signature
from app.world.model import WorldModel
from app.domain.world import WorldState
from app.runtime.registry import Tool


def action(idx: str = "1") -> dict:
    return ActionSpec(
        action_id=f"runtime-{idx}", capability="calculator", tool="calculator",
        parameters=(("expression", "2+2"),), preconditions=(), expected_effects=("calculated",),
        risk="low", cost=1.0, reversible=True, uncertainty=1.0,
    ).to_dict()


def transition(state: str, nxt: str, *, ok=True, verified=True, duration=0.2, reward=None, failure=""):
    out = {"ok": ok, "verified": verified, "duration_ms": duration * 1000, "error": "" if ok else "failed"}
    return {
        "state_before": state, "action": action(), "state_after": nxt,
        "outcome": out, "verified": verified, "reward": reward,
        "failure_class": failure, "timestamp": "2026-09-30T12:00:00+00:00",
    }


def test_model_aggregates_distribution_and_does_not_overwrite(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    assert model.learn_transition(transition("S", "S1", duration=1.0))
    assert model.learn_transition(transition("S", "S1", duration=3.0))
    assert model.learn_transition(transition("S", "S2", ok=False, verified=False, failure="tool_failure", duration=2.0))

    pred = model.predict("S", action())
    assert pred is not None
    assert pred.predicted_state == "S1"
    assert pred.evidence_count == 3
    assert 0.0 < pred.next_state_probability < 1.0
    assert 0.0 < pred.confidence < 1.0
    assert pred.uncertainty > 0.0
    assert abs(pred.expected_duration_seconds - 2.0) < 1e-9
    assert pred.failure_distribution


def test_contexts_are_not_collapsed(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    assert model.learn_transition(transition("C1", "N1"))
    assert model.learn_transition(transition("C2", "N2"))
    assert model.predict("C1", action()).predicted_state == "N1"
    assert model.predict("C2", action()).predicted_state == "N2"
    assert model.predict("unknown", action()) is None


def test_one_observation_cannot_create_high_confidence(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    model.learn_transition(transition("S", "N"))
    pred = model.predict("S", action())
    assert pred is not None
    assert pred.confidence < 0.5
    assert pred.uncertainty > 0.5


def test_action_signature_ignores_runtime_identity_but_respects_parameters():
    a = action("a")
    b = action("b")
    assert action_signature(a) == action_signature(b)
    c = dict(a)
    c["parameters"] = {"expression": "9+9"}
    assert action_signature(a) != action_signature(c)


def test_world_model_uses_learned_prediction_when_evidence_exists(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    world = WorldState()
    tool = Tool(name="calculator", description="calc", params={"expression": "str"}, fn=lambda expression: 4,
                capability="calculator", produces=("calculated",), cost=1.0)
    runtime_action = {
        "capability": tool.capability or tool.name, "tool": tool.name,
        "parameters": [("expression", "2+2")], "preconditions": [],
        "expected_effects": ["calculated"], "risk": tool.risk, "cost": tool.cost,
        "reversible": True,
    }
    model.learn_transition({
        "state_before": world.fingerprint(), "action": runtime_action, "state_after": "learned-next",
        "outcome": {"ok": True, "verified": True, "duration_ms": 100}, "verified": True,
        "timestamp": "2026-09-30T12:00:00+00:00",
    })
    prediction = WorldModel(learned_model=model).predict(tool, {"expression": "2+2"}, world)
    assert prediction.source == "learned-transition-model"
    assert prediction.confidence < 0.5
    assert "مشاهدة فعلية" in " ".join(prediction.warnings)


def test_manager_learns_real_episode_and_reuses_it_on_next_prediction(tmp_path):
    from types import SimpleNamespace
    from app.domain.plan import Plan, PlanStep
    from app.domain.world import WorldState
    from app.learning.manager import SelfImprovementManager

    manager = SelfImprovementManager(learning_path=tmp_path / "learning.db", bank_path=tmp_path / "skills.db")
    class Memory:
        def __init__(self):
            self.rows = []
        def effects(self, run_id):
            return self.rows

    mem = Memory()
    state = SimpleNamespace(
        run_id="episode-1", goal="calculate result", status="completed", replans=0,
        world=WorldState(),
        plan=Plan([PlanStep("s1", "calculator", {"expression": "2+2"}, status="done", capability="calculation")]),
    )
    before = state.world.fingerprint()
    mem.rows = [{
        "step_id": "s1", "attempt": 1, "tool": "calculator", "args": {"expression": "2+2"},
        "output": 4, "ok": True, "verified": True, "error": None, "duration_ms": 20.0,
        "ts": "2026-09-30T00:00:00", "state_before": before, "state_after": "NEXT-STATE",
    }]
    registry = {"calculator": type("Tool", (), {
        "capability": "calculation", "preconditions": (), "produces": (), "risk": "low",
        "cost": 1.0, "reversible": False,
    })()}
    result1 = manager.observe_run(state, mem, registry=registry)
    assert result1["transition_model_updates"] == 1
    assert result1["value_learning"]["transitions"] == 1
    learned = manager.transition_model.predict(before, result1["experience"]["transitions"][0]["action"])
    assert learned is not None
    assert learned.predicted_state == "NEXT-STATE"

    # The next observed transition for the same state/action carries the learned prediction.
    state.run_id = "episode-2"
    result2 = manager.observe_run(state, mem, registry=registry)
    assert result2["experience"]["transitions"][0]["predicted_state"] == "NEXT-STATE"

from __future__ import annotations

from app.brain.models import ActionSpec
from app.learning.store import LearningStore
from app.learning.transition_model import LearnedTransitionModel
from app.learning.value_model import ValueModel
from app.world.counterfactual import CounterfactualSimulator


def action(tool: str, value=1) -> dict:
    return ActionSpec(
        action_id=f"runtime-{tool}-{value}",
        capability="demo",
        tool=tool,
        parameters=(("value", value),),
        preconditions=(),
        expected_effects=("next",),
        risk="low",
        cost=1.0,
        reversible=True,
        uncertainty=1.0,
    ).to_dict()


def transition(before: str, after: str, tool: str = "go", *, reward: float = 0.2) -> dict:
    return {
        "state_before": before,
        "action": action(tool),
        "state_after": after,
        "outcome": {"ok": True, "verified": True, "duration_ms": 1000, "attempt": 1},
        "verified": True,
        "reward": reward,
        "failure_class": "",
        "timestamp": "2026-09-30T12:00:00+00:00",
    }


def learn(model: LearnedTransitionModel, before: str, after: str, tool: str = "go", count: int = 5, reward: float = 0.2):
    for _ in range(count):
        assert model.learn_transition(transition(before, after, tool, reward=reward))


def test_multi_step_counterfactual_rollout_uses_only_learned_transitions(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    vm = ValueModel(store)
    learn(tm, "S0", "S1", "go", count=5, reward=0.2)
    learn(tm, "S1", "S2", "finish", count=5, reward=1.0)

    simulator = CounterfactualSimulator(tm, vm, max_depth=3)
    result = simulator.simulate("S0", [action("go"), action("finish")])

    assert result.side_effect_free is True
    assert result.fully_supported is True
    assert result.explored_depth == 2
    assert len(result.branches) == 1
    branch = result.branches[0]
    assert branch.state_signature == "S2"
    assert branch.depth == 2
    assert [step.predicted_state for step in branch.steps] == ["S1", "S2"]
    assert branch.discounted_return > 0


def test_stochastic_model_produces_multiple_counterfactual_branches(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    for _ in range(7):
        assert tm.learn_transition(transition("S", "A", reward=0.5))
    for _ in range(3):
        assert tm.learn_transition(transition("S", "B", reward=-0.2))

    simulator = CounterfactualSimulator(tm, max_depth=1, branch_probability_floor=0.01)
    result = simulator.simulate("S", [action("go")])

    states = {branch.state_signature for branch in result.branches}
    assert {"A", "B"}.issubset(states)
    assert abs(sum(branch.probability for branch in result.branches) - 1.0) < 1e-9
    assert result.fully_supported is True


def test_unknown_state_action_is_truncated_not_invented(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    simulator = CounterfactualSimulator(tm, max_depth=2)

    result = simulator.simulate("UNKNOWN", [action("go")])

    assert result.fully_supported is False
    assert result.unsupported_probability == 1.0
    assert len(result.branches) == 1
    assert result.branches[0].status == "truncated"
    assert result.branches[0].termination_reason == "unknown_state_action"
    assert result.branches[0].steps == ()


def test_low_confidence_model_is_not_allowed_to_roll_out(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    # One observation intentionally remains low-confidence in Phase 3.
    assert tm.learn_transition(transition("S", "G"))
    simulator = CounterfactualSimulator(tm, max_depth=2, min_prediction_confidence=0.25)

    result = simulator.simulate("S", [action("go")])

    assert result.fully_supported is False
    assert result.branches[0].status == "truncated"
    assert result.branches[0].termination_reason == "low_model_confidence"


def test_accumulated_uncertainty_truncates_long_rollout(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    learn(tm, "S0", "S1", "go", count=2)
    learn(tm, "S1", "S2", "finish", count=2)
    simulator = CounterfactualSimulator(
        tm, max_depth=2, max_accumulated_uncertainty=0.55, min_prediction_confidence=0.01
    )

    result = simulator.simulate("S0", [action("go"), action("finish")])

    assert result.fully_supported is False
    assert result.branches[0].status == "truncated"
    assert result.branches[0].termination_reason == "accumulated_uncertainty"


def test_simulation_is_read_only_and_does_not_create_learning_records(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    learn(tm, "S", "G", count=5)
    before_model = tm.inspect("S", action("go"))
    before_stats = store.transition_model_stats()
    simulator = CounterfactualSimulator(tm)

    _ = simulator.simulate("S", [action("go")])

    after_model = tm.inspect("S", action("go"))
    after_stats = store.transition_model_stats()
    assert after_model["observation_count"] == before_model["observation_count"]
    assert after_model["prediction_count"] == before_model["prediction_count"]
    assert after_stats == before_stats
    assert store.prediction_error_stats()["predictions"] == 0


def test_alternatives_are_simulated_independently_without_selecting_one(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    tm = LearnedTransitionModel(store)
    learn(tm, "S", "GOOD", "good", count=5, reward=1.0)
    learn(tm, "S", "BAD", "bad", count=5, reward=-1.0)
    simulator = CounterfactualSimulator(tm, max_depth=1)

    results = simulator.simulate_alternatives(
        "S",
        [[action("good")], [action("bad")]],
    )

    assert len(results) == 2
    assert results[0].branches[0].state_signature == "GOOD"
    assert results[1].branches[0].state_signature == "BAD"
    # Phase 6 exposes evidence; selection/ranking belongs to the planner phase.
    assert all(result.side_effect_free for result in results)

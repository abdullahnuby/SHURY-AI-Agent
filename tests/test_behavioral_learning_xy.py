from __future__ import annotations

from pathlib import Path

from app.domain.world import WorldState
from app.learning.manager import SelfImprovementManager
from app.learning.store import LearningStore
from app.planning.model_based_planner import ModelBasedPlanner
from app.runtime.registry import Tool


def _action(name: str) -> dict:
    return {
        "action_id": f"{name}:behavioral-experiment",
        "capability": "finish",
        "tool": name,
        "parameters": {},
        "preconditions": [],
        "expected_effects": ["goal_reached"],
        "risk": "low",
        "reversible": True,
        "execution_time": 0.0,
        "cost": 1.0,
    }


def _transition(state: str, action: dict, *, success: bool, success_state: str, failure_state: str) -> dict:
    return {
        "state_before": state,
        "action": action,
        "state_after": success_state if success else failure_state,
        "outcome": {"ok": success, "verified": success},
        "verified": success,
        "reward": 1.0 if success else 0.0,
        "timestamp": "2026-09-30T00:00:00+00:00",
        "metadata": (),
    }


def _train_regime(manager: SelfImprovementManager, state: str, action_x: dict, action_y: dict,
                  success_x: int, success_y: int, *, rounds: int = 20,
                  success_state: str, failure_state: str) -> None:
    """Replay a deterministic schedule representing real observations from a changing bandit."""
    if not 0 <= success_x <= 10 or not 0 <= success_y <= 10:
        raise ValueError("success counts must be percentages in 10-trial blocks")
    for round_index in range(rounds):
        for action, successes in ((action_x, success_x), (action_y, success_y)):
            observed_success = (round_index % 10) < successes
            transition = _transition(
                state, action,
                success=observed_success,
                success_state=success_state,
                failure_state=failure_state,
            )
            manager.transition_model.learn_episode([transition])
            manager.value_model.learn_episode([transition], episode_reward=transition["reward"])


def test_behavior_changes_when_environment_reverses(tmp_path: Path):
    """Behavioral gate: learn X≈80%/Y≈20%, then adapt to X≈20%/Y≈80%."""
    manager = SelfImprovementManager(store=LearningStore(tmp_path / "learning.db"))
    registry = {
        name: Tool(
            name,
            "controlled behavioral experiment action",
            {},
            lambda: True,
            capability="finish",
            produces=("goal_reached",),
            match=lambda goal: "choose action" in str(goal).casefold(),
            verification_level="standard",
        )
        for name in ("action_x", "action_y")
    }
    world = WorldState(capabilities={"finish"})
    state = world.fingerprint()
    success_state = WorldState(capabilities={"finish", "goal_reached"}).fingerprint()
    failure_state = WorldState(capabilities={"finish", "failed"}).fingerprint()
    action_x, action_y = _action("action_x"), _action("action_y")

    _train_regime(
        manager, state, action_x, action_y, 8, 2,
        success_state=success_state, failure_state=failure_state,
    )
    planner = ModelBasedPlanner(manager.transition_model, manager.value_model, registry=registry, max_depth=1)
    phase_one = planner.plan("choose action", world)
    assert [step.tool for step in phase_one.steps] == ["action_x"]
    assert phase_one.diagnostics.get("selection") == "learned_action_values"

    _train_regime(
        manager, state, action_x, action_y, 2, 8,
        success_state=success_state, failure_state=failure_state,
    )
    phase_two = planner.plan("choose action", world)
    assert [step.tool for step in phase_two.steps] == ["action_y"]
    assert phase_two.diagnostics.get("selection") == "learned_action_values"

    x_prediction = manager.transition_model.predict(state, action_x)
    y_prediction = manager.transition_model.predict(state, action_y)
    assert x_prediction is not None and y_prediction is not None
    assert abs(x_prediction.success_probability - 0.50) < 0.01
    assert abs(y_prediction.success_probability - 0.50) < 0.01

    x_q = manager.value_model.predict_action(state, action_x)
    y_q = manager.value_model.predict_action(state, action_y)
    assert x_q is not None and y_q is not None
    assert y_q.value > x_q.value


def test_learned_policy_value_persists_and_reuses_new_weights(tmp_path: Path):
    path = tmp_path / "learning.db"
    manager = SelfImprovementManager(store=LearningStore(path))
    registry = {
        name: Tool(
            name, "controlled behavioral experiment action", {}, lambda: True,
            capability="finish", produces=("goal_reached",),
            match=lambda goal: "choose action" in str(goal).casefold(),
            verification_level="standard",
        )
        for name in ("left", "right")
    }
    world = WorldState(capabilities={"finish"})
    state = world.fingerprint()
    success_state = WorldState(capabilities={"finish", "goal_reached"}).fingerprint()
    left, right = _action("left"), _action("right")
    for _ in range(4):
        for action, success in ((left, True), (right, False)):
            t = _transition(state, action, success=success, success_state=success_state, failure_state=state)
            manager.transition_model.learn_episode([t])
            manager.value_model.learn_episode([t], episode_reward=t["reward"])
    reopened = SelfImprovementManager(store=LearningStore(path))
    planner = ModelBasedPlanner(reopened.transition_model, reopened.value_model, registry=registry, max_depth=1)
    plan = planner.plan("choose action", world)
    assert [step.tool for step in plan.steps] == ["left"]
    assert plan.diagnostics.get("selection") == "learned_action_values"


def test_behavioral_experiment_is_learning_driven_not_hardcoded(tmp_path: Path):
    """Both arms must be learned edges; removing one arm removes it from candidate planning."""
    manager = SelfImprovementManager(store=LearningStore(tmp_path / "learning.db"))
    registry = {
        name: Tool(name, "experiment action", {}, lambda: True, capability="finish",
                   produces=("goal_reached",),
                   match=lambda goal: "choose action" in str(goal).casefold())
        for name in ("action_x", "action_y")
    }
    world = WorldState(capabilities={"finish"})
    state = world.fingerprint()
    next_state = WorldState(capabilities={"finish", "goal_reached"}).fingerprint()
    x = _action("action_x")
    manager.transition_model.learn_episode([_transition(state, x, success=True, success_state=next_state, failure_state=state)])

    planner = ModelBasedPlanner(manager.transition_model, manager.value_model, registry=registry, max_depth=1)
    learned_actions = manager.transition_model.actions_for_state(state)
    assert [row["action"]["tool"] for row in learned_actions] == ["action_x"]
    # A single observation is intentionally insufficient for a certified model-based decision.
    result = planner.plan("choose action", world)
    assert not result.steps
    assert result.planner == "v23-model-based-reject"

from __future__ import annotations

from pathlib import Path
import random

from app.domain.world import WorldState
from app.learning.manager import SelfImprovementManager
from app.learning.store import LearningStore
from app.learning.bandit import NonStationaryBandit
from app.planning.model_based_planner import ModelBasedPlanner
from app.runtime.registry import Tool


def _action(name: str) -> dict:
    return {
        "action_id": f"{name}:weight-test",
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


def _transition(state: str, action: dict, *, ok: bool, next_state: str, reward: float) -> dict:
    return {
        "state_before": state,
        "action": action,
        "state_after": next_state if ok else state,
        "outcome": {"ok": ok, "verified": ok},
        "verified": ok,
        "reward": reward,
        "timestamp": "2026-10-05T00:00:00+00:00",
        "metadata": (),
    }


def _registry(names: tuple[str, ...]) -> dict[str, Tool]:
    return {
        name: Tool(
            name,
            "weight-learning action",
            {},
            lambda: True,
            capability="finish",
            produces=("goal_reached",),
            match=lambda goal: "choose" in str(goal).casefold(),
            verification_level="standard",
        )
        for name in names
    }


def test_action_values_are_real_persistent_learned_parameters(tmp_path: Path):
    path = tmp_path / "learning.db"
    manager = SelfImprovementManager(store=LearningStore(path))
    world = WorldState(capabilities={"finish"})
    state = world.fingerprint()
    good = _action("new-alpha")
    bad = _action("new-beta")
    goal_state = WorldState(capabilities={"finish", "goal_reached"}).fingerprint()

    manager.value_model.learn_episode([_transition(state, good, ok=True, next_state=goal_state, reward=1.0)])
    manager.value_model.learn_episode([_transition(state, bad, ok=False, next_state=state, reward=-0.5)])
    before = manager.value_model.predict_action(state, good)
    assert before is not None
    assert before.visits == 1

    manager.value_model.learn_episode([_transition(state, good, ok=True, next_state=goal_state, reward=1.0)])
    after = SelfImprovementManager(store=LearningStore(path)).value_model.predict_action(state, good)
    assert after is not None
    assert after.visits == 2
    assert after.value > before.value


def test_planner_choice_flips_from_new_outcomes_without_action_name_rules(tmp_path: Path):
    manager = SelfImprovementManager(store=LearningStore(tmp_path / "learning.db"))
    names = ("unseen-left", "unseen-right")
    registry = _registry(names)
    world = WorldState(capabilities={"finish"})
    state = world.fingerprint()
    goal_state = WorldState(capabilities={"finish", "goal_reached"}).fingerprint()
    left, right = (_action(name) for name in names)

    for _ in range(4):
        manager.transition_model.learn_episode([_transition(state, left, ok=True, next_state=goal_state, reward=1.0)])
        manager.value_model.learn_episode([_transition(state, left, ok=True, next_state=goal_state, reward=1.0)])
        manager.transition_model.learn_episode([_transition(state, right, ok=False, next_state=state, reward=0.0)])
        manager.value_model.learn_episode([_transition(state, right, ok=False, next_state=state, reward=0.0)])

    planner = ModelBasedPlanner(manager.transition_model, manager.value_model, registry=registry, max_depth=1)
    first = planner.plan("choose", world)
    assert [step.tool for step in first.steps] == ["unseen-left"]
    assert first.diagnostics["selection"] == "learned_action_values"

    for _ in range(8):
        manager.transition_model.learn_episode([_transition(state, left, ok=False, next_state=state, reward=0.0)])
        manager.value_model.learn_episode([_transition(state, left, ok=False, next_state=state, reward=0.0)])
        manager.transition_model.learn_episode([_transition(state, right, ok=True, next_state=goal_state, reward=1.0)])
        manager.value_model.learn_episode([_transition(state, right, ok=True, next_state=goal_state, reward=1.0)])

    second = planner.plan("choose", world)
    assert [step.tool for step in second.steps] == ["unseen-right"]
    assert second.diagnostics["selection"] == "learned_action_values"


def test_exploration_converges_to_best_action_from_feedback(tmp_path: Path):
    bandit = NonStationaryBandit(("candidate-a", "candidate-b"), exploration=1.0, detector_threshold=7.0)
    seed = 23
    rng = random.Random(seed)
    chosen: list[str] = []
    for _ in range(200):
        arm = bandit.choose_arm()
        chosen.append(arm)
        probability = 0.80 if arm == "candidate-b" else 0.20
        reward = 1.0 if rng.random() < probability else 0.0
        bandit.observe_reward(arm, reward)

    assert chosen[40:].count("candidate-b") > chosen[40:].count("candidate-a")
    assert chosen[-50:].count("candidate-b") >= 35


def test_no_evidence_does_not_claim_learned_policy_control(tmp_path: Path):
    manager = SelfImprovementManager(store=LearningStore(tmp_path / "learning.db"))
    registry = _registry(("cold-a", "cold-b"))
    world = WorldState(capabilities={"finish"})
    state = world.fingerprint()
    # A transition model edge is not enough to claim learned policy weights; action values need
    # observed visits as the policy parameterization used by final selection.
    action_a = _action("cold-a")
    action_b = _action("cold-b")
    goal_state = WorldState(capabilities={"finish", "goal_reached"}).fingerprint()
    for action, ok in ((action_a, True), (action_b, False)):
        transition = _transition(state, action, ok=ok, next_state=goal_state, reward=1.0 if ok else 0.0)
        manager.transition_model.learn_episode([transition])
        manager.transition_model.learn_episode([transition])
        manager.value_model.learn_episode([transition])
    planner = ModelBasedPlanner(manager.transition_model, manager.value_model, registry=registry, max_depth=1)
    result = planner.plan("choose", world)
    assert result.diagnostics["selection"] == "model_metrics_cold_start"

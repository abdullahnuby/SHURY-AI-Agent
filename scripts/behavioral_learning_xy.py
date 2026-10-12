from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.world import WorldState
from app.learning.manager import SelfImprovementManager
from app.learning.store import LearningStore
from app.planning.model_based_planner import ModelBasedPlanner
from app.runtime.registry import Tool


def action(name: str) -> dict:
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


def transition(state: str, act: dict, success: bool, success_state: str, failure_state: str) -> dict:
    return {
        "state_before": state,
        "action": act,
        "state_after": success_state if success else failure_state,
        "outcome": {"ok": success, "verified": success},
        "verified": success,
        "reward": 1.0 if success else 0.0,
        "timestamp": "2026-09-30T00:00:00+00:00",
        "metadata": (),
    }


def train(manager: SelfImprovementManager, state: str, x: dict, y: dict,
          x_successes: int, y_successes: int, *, rounds: int,
          success_state: str, failure_state: str) -> None:
    for round_index in range(rounds):
        for act, successes in ((x, x_successes), (y, y_successes)):
            success = (round_index % 10) < successes
            observed = transition(state, act, success, success_state, failure_state)
            manager.transition_model.learn_episode([observed])
            manager.value_model.learn_episode([observed], episode_reward=observed["reward"])


def run(rounds: int = 20) -> dict:
    with TemporaryDirectory(prefix="shury-xy-") as directory:
        manager = SelfImprovementManager(store=LearningStore(Path(directory) / "learning.db"))
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
        x, y = action("action_x"), action("action_y")
        planner = ModelBasedPlanner(manager.transition_model, manager.value_model, registry=registry, max_depth=1)

        train(manager, state, x, y, 8, 2, rounds=rounds,
              success_state=success_state, failure_state=failure_state)
        phase_one = planner.plan("choose action", world)

        train(manager, state, x, y, 2, 8, rounds=rounds,
              success_state=success_state, failure_state=failure_state)
        phase_two = planner.plan("choose action", world)

        px, py = manager.transition_model.predict(state, x), manager.transition_model.predict(state, y)
        qx, qy = manager.value_model.predict_action(state, x), manager.value_model.predict_action(state, y)
        result = {
            "experiment": "xy-reversal",
            "rounds_per_regime": rounds,
            "regime_a": {"action_x_success_rate": 0.8, "action_y_success_rate": 0.2,
                         "selected": phase_one.steps[0].tool if phase_one.steps else None},
            "regime_b": {"action_x_success_rate": 0.2, "action_y_success_rate": 0.8,
                         "selected": phase_two.steps[0].tool if phase_two.steps else None},
            "learned": {
                "action_x_success_probability": px.success_probability if px else None,
                "action_y_success_probability": py.success_probability if py else None,
                "action_x_value": qx.value if qx else None,
                "action_y_value": qy.value if qy else None,
            },
            "behavior_changed": (
                bool(phase_one.steps) and bool(phase_two.steps)
                and phase_one.steps[0].tool != phase_two.steps[0].tool
            ),
        }
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SHURY's deterministic X/Y behavioral-learning gate.")
    parser.add_argument("--rounds", type=int, default=20)
    args = parser.parse_args()
    if args.rounds < 10:
        raise SystemExit("--rounds must be >= 10")
    print(json.dumps(run(args.rounds), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

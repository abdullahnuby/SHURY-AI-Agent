from __future__ import annotations

from pathlib import Path

from app.learning.causal import ControlledCausalLearner
from app.learning.store import LearningStore
from app.learning.transition_model import LearnedTransitionModel


def _action(name: str) -> dict:
    return {
        "action_id": f"{name}:causal",
        "capability": name,
        "tool": name,
        "parameters": {},
        "preconditions": [],
        "expected_effects": ["goal"],
        "risk": "low",
        "reversible": True,
    }


def _transition(i: int, state: str, action: dict, ok: bool, next_state: str) -> dict:
    return {
        "transition_id": f"t-{i}",
        "state_before": state,
        "action": action,
        "state_after": next_state,
        "outcome": {"ok": ok, "verified": ok, "attempt": 1},
        "verified": ok,
        "reward": 1.0 if ok else 0.0,
        "prediction_error": 0.1 if not ok else 0.02,
    }


def test_g06_1_association_is_not_called_causal_without_matched_control(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    x, y = _action("X"), _action("Y")
    for i in range(8):
        model.learn_transition(_transition(i, "GOOD", x, True, "G"))
        model.learn_transition(_transition(100 + i, "BAD", y, False, "F"))
    estimate = ControlledCausalLearner(store, model).estimate("GOOD", x, y)
    assert estimate.association == 1.0
    assert estimate.controlled_causal_effect == 0.0
    assert estimate.confounding_risk == 1.0
    assert not estimate.usable


def test_g06_2_controlled_effect_and_counterfactual_replay_are_distinct(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    causal = ControlledCausalLearner(store, model)
    x, y = _action("X"), _action("Y")
    for i in range(8):
        model.learn_transition(_transition(i, "C", x, True, "G"))
        model.learn_transition(_transition(20 + i, "C", y, False, "F"))
    estimate = causal.estimate("C", x, y)
    replay = causal.replay_counterfactual("C", x, y)
    assert estimate.treatment_observations == 8
    assert estimate.control_observations == 8
    assert estimate.association > 0.6
    assert estimate.controlled_causal_effect > 0.6
    assert estimate.counterfactual_effect is not None and estimate.counterfactual_effect > 0.4
    assert replay["available"] is True
    assert replay["side_effects"] == 0
    assert replay["mode"] == "counterfactual-simulation-only"
    store.record_causal_effect(estimate.to_dict())
    persisted = store.causal_effects("C")
    assert len(persisted) == 1
    assert persisted[0]["controlled_causal_effect"] == estimate.controlled_causal_effect


def test_g06_3_counterfactual_replay_never_executes_runtime_side_effects(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    causal = ControlledCausalLearner(store, None)
    result = causal.replay_counterfactual("C", _action("X"), _action("Y"))
    assert result == {"available": False, "reason": "missing-transition-model", "side_effects": 0}

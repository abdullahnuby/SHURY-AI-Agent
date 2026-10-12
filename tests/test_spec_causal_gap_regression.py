from pathlib import Path

from app.learning.causal import ControlledCausalLearner
from app.learning.store import LearningStore
from app.learning.transition_model import action_signature


def _a(name):
    return {"capability": name, "tool": name, "parameters": {}, "preconditions": [], "expected_effects": [], "risk": "low", "reversible": True}


def _obs(store, state, action, i, ok):
    store.upsert_transition_observation(state_signature=state, action_signature=action_signature(action), action=action,
                                       next_state=f"n{i}", outcome_key=f"ok={str(ok).lower()}", failure_key=None if ok else "failure",
                                       ok=ok, verified=ok, duration_seconds=1.0, reward=1.0 if ok else 0.0,
                                       observed_at=f"2026-10-01T00:00:{i:02d}", transition_id=f"{state}:{action['tool']}:{i}")


def test_simpson_confounding_is_not_reported_as_controlled_causal_effect(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    treatment, control = _a("T"), _a("C")
    # Pooled association: T looks better (90% vs 45%).
    for i in range(90): _obs(store, "S_high", treatment, i, True)
    for i in range(10): _obs(store, "S_high", treatment, 100+i, False)
    for i in range(30): _obs(store, "S_low", control, i, True)
    for i in range(70): _obs(store, "S_low", control, 100+i, False)
    # Matched state S_high: T=90%, C=95% -> treatment is worse in the controlled context.
    for i in range(90): _obs(store, "S_match", treatment, i, True)
    for i in range(10): _obs(store, "S_match", treatment, 100+i, False)
    for i in range(95): _obs(store, "S_match", control, i, True)
    for i in range(5): _obs(store, "S_match", control, 100+i, False)
    # Add other state evidence with same actions to create the pooled association.
    for i in range(10): _obs(store, "S_other", treatment, 200+i, False)
    for i in range(70): _obs(store, "S_other", control, 200+i, False)
    estimate = ControlledCausalLearner(store).estimate("S_match", treatment, control)
    assert estimate.association > 0.0
    assert estimate.controlled_causal_effect < 0.0
    assert estimate.confounding_risk > 0.40

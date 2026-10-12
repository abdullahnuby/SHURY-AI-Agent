from pathlib import Path

from app.learning.store import LearningStore
from app.learning.transition_model import LearnedTransitionModel, action_signature
from app.learning.invalidation import ModelInvalidation


def _action():
    return {
        "capability": "lookup",
        "tool": "lookup_tool",
        "parameters": {"query": "x"},
        "preconditions": [],
        "expected_effects": ["lookup_done"],
        "risk": "low",
        "reversible": True,
    }


def _transition(i, *, state_after="s1", ok=True, reward=1.0):
    return {
        "transition_id": f"t{i}",
        "state_before": "s0",
        "action": _action(),
        "state_after": state_after,
        "outcome": {"ok": ok, "verified": ok, "duration_ms": 10, "attempt": 1},
        "verified": ok,
        "reward": reward,
        "timestamp": f"2026-09-30T00:00:{i:02d}",
    }


def _seed(store):
    model = LearnedTransitionModel(store)
    for i in range(12):
        model.learn_transition(_transition(i, state_after="s1", ok=True))
    sig = action_signature(_action())
    return model, "s0", sig


def test_prediction_error_spike_invalidates_model_and_increases_exploration(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model, state, sig = _seed(store)
    # Record a clean baseline then a severe sequence of unexpected predictions/outcomes.
    for i in range(12, 24):
        store.record_prediction_error({
            "transition_id": f"e{i}", "state_signature": state, "action_signature": sig,
            "predicted_state": "s1", "observed_state": "unexpected", "top_state_probability": 0.05,
            "top_state_hit": False, "state_observed_probability": 0.05, "state_log_loss": 1.0,
            "state_brier": 1.0, "predicted_success_probability": 0.9, "observed_success": False,
            "success_brier": 0.81, "predicted_verified_probability": 0.9, "observed_verified": False,
            "verified_brier": 0.81, "outcome_log_loss": 1.0, "duration_error": 0.0,
            "reward_error": 1.0, "value_error": 1.0, "total_error": 0.95, "surprise": 1.0,
            "confidence": 0.9, "uncertainty": 0.1, "evidence_count": 12, "created_at": f"2026-10-01T00:00:{i:02d}",
        })
    for i in range(12, 24):
        model.learn_transition(_transition(100 + i, state_after="unexpected", ok=False, reward=0.0))
    decision = ModelInvalidation(store, window=12, min_evidence=8).evaluate(state, sig)
    assert decision.invalidated is True
    assert decision.stale is True
    assert decision.exploration_multiplier > 1.0
    assert decision.relearn_required is True


def test_stale_model_relearns_after_fresh_real_evidence(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model, state, sig = _seed(store)
    store.invalidate_transition_model(state, sig, reason="distribution-shift", distribution_shift=0.8)
    row = store.get_transition_model(state, sig)
    assert row["stale"] is True
    for i in range(40, 43):
        model.learn_transition(_transition(i, state_after="s2", ok=True, reward=1.0))
    row = store.get_transition_model(state, sig)
    assert row["fresh_observations"] >= 3
    assert row["stale"] is False
    assert row["model_version"] > 1


def test_duplicate_transition_id_does_not_double_count(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    transition = _transition(1)
    model.learn_transition(transition)
    model.learn_transition(transition)
    row = store.get_transition_model("s0", action_signature(_action()))
    assert row["observation_count"] == 1


def test_stale_transition_invalidates_dependent_procedure(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    procedure = store.upsert_procedural_memory(
        task_family_signature="family-1", operation="ship", capability="lookup",
        workflow=({"tool": "lookup_tool", "capability": "lookup", "depends_on": []}, {"tool": "finish", "capability": "finish", "depends_on": ["lookup_tool"]}),
        trigger_conditions=("family-1",), termination_conditions=("goal_verified",),
        recovery_strategy=("replan",), context_boundary=("environment:e1",),
        evidence_run_ids=("r1", "r2"), success=True, confidence=0.90, key="proc:lookup",
    )
    store.upsert_procedural_memory(
        task_family_signature="family-1", operation="ship", capability="lookup",
        workflow=({"tool": "other_tool", "capability": "other", "depends_on": []}, {"tool": "finish", "capability": "finish", "depends_on": ["other_tool"]}),
        trigger_conditions=("family-1",), termination_conditions=("goal_verified",),
        recovery_strategy=("replan",), context_boundary=("environment:e1",),
        evidence_run_ids=("r3", "r4"), success=True, confidence=0.90, key="proc:other",
    )
    model = LearnedTransitionModel(store)
    for i in range(12):
        model.learn_transition(_transition(i, state_after="s1", ok=True))
    sig = action_signature(_action())
    # Inject strong drift evidence and then use the canonical invalidation bridge.
    for i in range(12, 24):
        store.record_prediction_error({
            "transition_id": f"e{i}", "state_signature": "s0", "action_signature": sig,
            "predicted_state": "s1", "observed_state": "unexpected", "top_state_probability": 0.05,
            "top_state_hit": False, "state_observed_probability": 0.05, "state_log_loss": 1.0,
            "state_brier": 1.0, "predicted_success_probability": 0.9, "observed_success": False,
            "success_brier": 0.81, "predicted_verified_probability": 0.9, "observed_verified": False,
            "verified_brier": 0.81, "outcome_log_loss": 1.0, "duration_error": 0.0,
            "reward_error": 1.0, "value_error": 1.0, "total_error": 0.95, "surprise": 1.0,
            "confidence": 0.9, "uncertainty": 0.1, "evidence_count": 12, "created_at": f"2026-10-01T00:00:{i:02d}",
        })
        model.learn_transition(_transition(100 + i, state_after="unexpected", ok=False, reward=0.0))
    decision = ModelInvalidation(store, window=12, min_evidence=8).evaluate_transition(_transition(999, state_after="unexpected", ok=False, reward=0.0))
    assert decision.stale is True
    rows = store.procedural_memories(task_family_signature="family-1", include_invalidated=False)
    assert [row["key"] for row in rows] == ["proc:other"]
    all_rows = {row["key"]: row for row in store.procedural_memories(task_family_signature="family-1", include_invalidated=True)}
    assert all_rows["proc:lookup"]["status"] == "invalidated"


def test_regime_flip_weakens_old_evidence_and_does_not_reinvalidate(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    state, action = "s0", _action()
    for i in range(20):
        model.learn_transition(_transition(i, state_after="s1", ok=True, reward=1.0))
    sig = action_signature(action)
    first = ModelInvalidation(store, window=6, min_evidence=8, relearn_evidence=3).evaluate(state, sig)
    assert first.invalidated is False
    first_invalidation_count = store.get_transition_model(state, sig)["invalidation_count"]
    # Regime flip: 40 consecutive real failures. The first drift event invalidates once;
    # later observations must not repeatedly reset fresh evidence or bump invalidation_count.
    first_stale_at = None
    for i in range(20, 60):
        model.learn_transition(_transition(i, state_after="s2", ok=False, reward=0.0))
        decision = ModelInvalidation(store, window=6, min_evidence=8, relearn_evidence=3).evaluate(state, sig)
        if decision.stale and first_stale_at is None:
            first_stale_at = i - 19
    assert first_stale_at == 3
    row = store.get_transition_model(state, sig)
    assert row["invalidation_count"] == first_invalidation_count + 1
    assert row["fresh_observations"] >= 3
    assert row["regime_baseline_observations"] == 20
    prediction = model.predict(state, action)
    assert prediction is not None
    assert prediction.success_probability < 0.20
    assert prediction.confidence < 0.70
    assert decision.stale is True


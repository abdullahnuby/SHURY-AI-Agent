from __future__ import annotations

from app.brain.models import ActionSpec
from app.learning.prediction_error import PredictionErrorModel
from app.learning.store import LearningStore
from app.learning.transition_model import LearnedTransitionModel


def action(name: str = "do", parameter=2) -> dict:
    return ActionSpec(
        action_id=f"runtime-{name}", capability="demo", tool=name,
        parameters=(("value", parameter),), preconditions=(), expected_effects=("next",),
        risk="low", cost=1.0, reversible=True, uncertainty=1.0,
    ).to_dict()


def tr(before: str, after: str, tool: str = "do", *, ok=True, verified=True,
       duration=1.0, reward=0.5) -> dict:
    return {
        "state_before": before,
        "action": action(tool),
        "state_after": after,
        "outcome": {
            "ok": ok, "verified": verified, "duration_ms": duration * 1000,
            "attempt": 1, "error": "" if ok else "failed",
        },
        "verified": verified,
        "reward": reward,
        "failure_class": "" if ok else "execution",
        "timestamp": "2026-09-30T12:00:00+00:00",
    }


def test_transition_prediction_exposes_distribution_for_formal_scoring(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    for _ in range(3):
        assert model.learn_transition(tr("S", "G"))
    prediction = model.predict("S", action())
    assert prediction is not None
    assert prediction.next_state_distribution
    assert abs(sum(prob for _, prob in prediction.next_state_distribution) - 1.0) < 1e-9
    assert prediction.predicted_state == "G"


def test_prediction_error_is_low_for_expected_observation_and_high_for_surprise(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    scorer = PredictionErrorModel(store, transition_model=model)
    for _ in range(5):
        model.learn_transition(tr("S", "G", reward=0.5))

    expected_prediction = model.predict("S", action())
    expected = scorer.score_prediction(expected_prediction, tr("S", "G", reward=0.5), transition_id="expected")
    unexpected = scorer.score_prediction(expected_prediction, tr("S", "BAD", ok=False, verified=False, reward=-0.5), transition_id="unexpected")

    assert expected.prediction_available
    assert unexpected.prediction_available
    assert expected.total_error < unexpected.total_error
    assert unexpected.surprise > expected.surprise
    assert unexpected.state_log_loss > expected.state_log_loss
    assert unexpected.success_brier > expected.success_brier


def test_prediction_error_feedback_reduces_future_confidence(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    scorer = PredictionErrorModel(store, transition_model=model)
    for _ in range(5):
        model.learn_transition(tr("S", "G"))

    before = model.predict("S", action())
    assert before is not None
    bad = scorer.score_prediction(before, tr("S", "BAD", ok=False, verified=False, reward=-0.5), transition_id="bad")
    assert store.record_prediction_error(bad.to_dict())
    after = model.predict("S", action())
    assert after is not None
    assert after.confidence < before.confidence
    assert after.uncertainty > before.uncertainty
    assert store.get_transition_model(before.state_signature, before.action_signature)["prediction_count"] == 1


def test_calibration_is_computed_from_prediction_outcomes(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    scorer = PredictionErrorModel(store, transition_model=model)
    for _ in range(5):
        model.learn_transition(tr("S", "G"))
    prediction = model.predict("S", action())
    assert prediction is not None

    # Four hits and one miss: the recorded top-state confidence is intentionally imperfectly calibrated.
    outcomes = ["G", "G", "G", "G", "BAD"]
    for index, observed in enumerate(outcomes):
        event = tr("S", observed, ok=observed == "G", verified=observed == "G", reward=0.5 if observed == "G" else -0.5)
        error = scorer.score_prediction(prediction, event, transition_id=f"cal-{index}")
        assert store.record_prediction_error(error.to_dict())

    calibration = scorer.calibration(limit=100)
    assert calibration["sample_count"] == 5
    assert calibration["next_state"]["ece"] > 0
    assert calibration["bins"]


def test_annotate_episode_persists_error_before_transition_learning(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    scorer = PredictionErrorModel(store, transition_model=model)
    for _ in range(5):
        model.learn_transition(tr("S", "G"))

    transitions = [tr("S", "BAD", ok=False, verified=False, reward=-0.5)]
    annotated, result = scorer.annotate_episode(transitions)
    assert result.scored_predictions == 1
    assert result.new_error_records == 1
    assert annotated[0]["prediction_error"] > 0
    persisted = store.recent_prediction_errors(limit=1)[0]
    assert persisted["total_error"] == annotated[0]["prediction_error"]
    model_row = store.get_transition_model(*__import__("app.learning.transition_model", fromlist=["model_key"]).model_key("S", action()))
    assert model_row["prediction_count"] == 1
    assert model_row["observation_count"] == 5


def test_runtime_snapshot_is_side_effect_free_and_formal(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    model = LearnedTransitionModel(store)
    for _ in range(5):
        model.learn_transition(tr("S", "G"))
    prediction = model.predict("S", action())
    assert prediction is not None
    snapshot = PredictionErrorModel.score_runtime_snapshot(
        prediction.to_dict(), observed_state="BAD", ok=False, verified=False, duration_seconds=10.0,
    )
    assert snapshot["available"]
    assert snapshot["prediction_error"] > 0
    assert snapshot["surprise"] > 0
    assert store.prediction_error_stats()["predictions"] == 0

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .transition_model import LearnedTransitionModel, TransitionPrediction, action_signature


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _log_loss(probability: float, *, scale: float = 6.0) -> float:
    p = max(1e-6, min(1.0, float(probability)))
    return _clamp(-math.log(p) / max(1e-6, float(scale)))


def _brier_binary(probability: float, observed: bool) -> float:
    return _clamp((float(probability) - float(bool(observed))) ** 2)


def _brier_categorical(distribution: dict[str, float], observed_state: str) -> float:
    if not distribution:
        return 0.0
    score = 0.0
    for state, probability in distribution.items():
        target = 1.0 if str(state) == str(observed_state) else 0.0
        score += (float(probability) - target) ** 2
    # Multiclass Brier score has a maximum approaching 2; normalize to [0, 1].
    return _clamp(score / 2.0)


@dataclass(frozen=True)
class PredictionError:
    """Formal pre-update prediction error for one observed transition."""
    transition_id: str
    state_signature: str
    action_signature: str
    predicted_state: str | None
    observed_state: str
    top_state_probability: float
    top_state_hit: bool
    state_observed_probability: float
    state_log_loss: float
    state_brier: float
    predicted_success_probability: float
    observed_success: bool
    success_brier: float
    predicted_verified_probability: float
    observed_verified: bool
    verified_brier: float
    outcome_log_loss: float
    duration_error: float
    reward_error: float
    value_error: float | None
    total_error: float
    surprise: float
    confidence: float
    uncertainty: float
    evidence_count: int
    prediction_available: bool
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PredictionLearningResult:
    transitions: int
    scored_predictions: int
    new_error_records: int
    mean_error: float
    mean_surprise: float
    high_error_events: int
    algorithm: str = "pre-update predictive scoring + online error feedback"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PredictionErrorModel:
    """Scores learned predictions against verified runtime observations and feeds error back.

    Critical ordering rule: the prediction is produced from the model state *before* the
    current observation is learned. The error record is then persisted, and only afterwards
    is the transition allowed to update the dynamics model. This prevents self-evaluation from
    leaking the answer into the prediction being graded.
    """

    WEIGHTS = {
        "state_log_loss": 0.22,
        "state_brier": 0.18,
        "success_brier": 0.14,
        "verified_brier": 0.10,
        "outcome_log_loss": 0.08,
        "duration_error": 0.08,
        "reward_error": 0.08,
        "value_error": 0.12,
    }

    def __init__(self, store, *, transition_model: LearnedTransitionModel | None = None,
                 value_model=None):
        self.store = store
        self.transition_model = transition_model or LearnedTransitionModel(store)
        self.value_model = value_model

    @staticmethod
    def _actual_outcome_key(transition: dict[str, Any]) -> str:
        outcome = transition.get("outcome") or {}
        if not isinstance(outcome, dict):
            outcome = {}
        return "|".join((
            "ok=" + str(bool(outcome.get("ok", transition.get("verified") is True))).lower(),
            "verified=" + str(bool(outcome.get("verified", transition.get("verified") is False))).lower(),
            "failure=" + str(transition.get("failure_class") or ""),
        ))

    @classmethod
    def score_prediction(cls, prediction: TransitionPrediction | None,
                         transition: dict[str, Any], *, transition_id: str | None = None,
                         value_model=None) -> PredictionError:
        state_signature = str(transition.get("state_before") or "")
        action = transition.get("action") or {}
        action_sig = action_signature(action if isinstance(action, dict) else {})
        observed_state = str(transition.get("state_after") or "")
        outcome = transition.get("outcome") or {}
        if not isinstance(outcome, dict):
            outcome = {}
        observed_success = bool(outcome.get("ok", False))
        observed_verified = bool(transition.get("verified", outcome.get("verified", False)))
        observed_duration = max(0.0, float(outcome.get("duration_ms", 0.0) or 0.0) / 1000.0)
        observed_reward = transition.get("reward")

        transition_id = str(transition_id or transition.get("transition_id") or "")
        if prediction is None or not observed_state:
            return cls._no_prediction(
                transition_id=transition_id,
                state_signature=state_signature,
                action_signature=action_sig,
                observed_state=observed_state,
            )

        distribution = {str(k): _clamp(float(v)) for k, v in prediction.next_state_distribution}
        if distribution:
            total = sum(distribution.values())
            if total > 0:
                distribution = {k: v / total for k, v in distribution.items()}
        observed_probability = distribution.get(observed_state, 0.0)
        state_nll = _log_loss(observed_probability)
        state_brier = _brier_categorical(distribution, observed_state)
        success_brier = _brier_binary(prediction.success_probability, observed_success)
        verified_brier = _brier_binary(prediction.verified_probability, observed_verified)

        actual_outcome = cls._actual_outcome_key(transition)
        outcome_distribution = dict(prediction.outcome_distribution)
        outcome_probability = float(outcome_distribution.get(actual_outcome, 0.0))
        outcome_nll = _log_loss(outcome_probability)

        duration_error = 0.0
        if prediction.expected_duration_seconds > 0.0 or observed_duration > 0.0:
            duration_error = _clamp(
                abs(float(prediction.expected_duration_seconds) - observed_duration)
                / max(1.0, float(prediction.expected_duration_seconds), observed_duration)
            )

        reward_error = 0.0
        if prediction.predicted_reward is not None and isinstance(observed_reward, (int, float)):
            reward_error = _clamp(abs(float(prediction.predicted_reward) - float(observed_reward)) / 2.0)

        value_error = None
        value_model = value_model
        if value_model is not None and prediction.predicted_state:
            try:
                predicted_value = value_model.predict_state(prediction.predicted_state)
                observed_value = value_model.predict_state(observed_state)
                if predicted_value is not None and observed_value is not None:
                    value_error = _clamp(
                        abs(predicted_value.value - observed_value.value)
                        / max(1.0, abs(predicted_value.value), abs(observed_value.value))
                    )
            except Exception:
                value_error = None

        components = {
            "state_log_loss": state_nll,
            "state_brier": state_brier,
            "success_brier": success_brier,
            "verified_brier": verified_brier,
            "outcome_log_loss": outcome_nll,
            "duration_error": duration_error,
            "reward_error": reward_error,
        }
        weights = dict(cls.WEIGHTS)
        if value_error is None:
            weights.pop("value_error", None)
        else:
            components["value_error"] = value_error
        denominator = sum(weights.values()) or 1.0
        total_error = _clamp(sum(weights[key] * components[key] for key in weights) / denominator)
        # Surprise is specifically confidence-weighted: an error from a confident model is
        # more informative than the same error from an already-uncertain model.
        surprise = _clamp(total_error * (0.5 + 0.5 * _clamp(prediction.confidence)))
        timestamp = str(transition.get("timestamp") or _now())
        return PredictionError(
            transition_id=transition_id,
            state_signature=state_signature,
            action_signature=action_sig,
            predicted_state=prediction.predicted_state,
            observed_state=observed_state,
            top_state_probability=_clamp(prediction.next_state_probability),
            top_state_hit=prediction.predicted_state == observed_state,
            state_observed_probability=_clamp(observed_probability),
            state_log_loss=round(state_nll, 6),
            state_brier=round(state_brier, 6),
            predicted_success_probability=_clamp(prediction.success_probability),
            observed_success=observed_success,
            success_brier=round(success_brier, 6),
            predicted_verified_probability=_clamp(prediction.verified_probability),
            observed_verified=observed_verified,
            verified_brier=round(verified_brier, 6),
            outcome_log_loss=round(outcome_nll, 6),
            duration_error=round(duration_error, 6),
            reward_error=round(reward_error, 6),
            value_error=(round(value_error, 6) if value_error is not None else None),
            total_error=round(total_error, 6),
            surprise=round(surprise, 6),
            confidence=round(_clamp(prediction.confidence), 6),
            uncertainty=round(_clamp(prediction.uncertainty), 6),
            evidence_count=int(prediction.evidence_count),
            prediction_available=True,
            created_at=timestamp,
        )

    @classmethod
    def score_runtime_snapshot(cls, snapshot: dict[str, Any] | None, *, observed_state: str,
                               ok: bool, verified: bool, duration_seconds: float) -> dict[str, Any]:
        """Score the immediately observed runtime result without persisting or learning it.

        This path is intentionally side-effect free. The durable pre-update score is produced
        later by :meth:`annotate_episode`, after the runtime has closed the episode boundary.
        """
        if not isinstance(snapshot, dict) or not observed_state:
            return {"available": False, "prediction_error": 0.0, "surprise": 0.0}
        distribution = {str(k): _clamp(float(v)) for k, v in (snapshot.get("next_state_distribution") or [])}
        total = sum(distribution.values())
        if total > 0:
            distribution = {k: v / total for k, v in distribution.items()}
        observed_probability = distribution.get(str(observed_state), 0.0)
        state_log_loss = _log_loss(observed_probability)
        state_brier = _brier_categorical(distribution, str(observed_state))
        success_brier = _brier_binary(float(snapshot.get("success_probability", 0.0)), bool(ok))
        verified_brier = _brier_binary(float(snapshot.get("verified_probability", 0.0)), bool(verified))
        duration_error = _clamp(
            abs(float(snapshot.get("expected_duration_seconds", 0.0) or 0.0) - max(0.0, float(duration_seconds)))
            / max(1.0, float(snapshot.get("expected_duration_seconds", 0.0) or 0.0), max(0.0, float(duration_seconds)))
        )
        components = {
            "state_log_loss": state_log_loss,
            "state_brier": state_brier,
            "success_brier": success_brier,
            "verified_brier": verified_brier,
            "duration_error": duration_error,
        }
        weights = {"state_log_loss": 0.32, "state_brier": 0.24, "success_brier": 0.18, "verified_brier": 0.12, "duration_error": 0.14}
        total_error = _clamp(sum(weights[k] * components[k] for k in weights))
        confidence = _clamp(float(snapshot.get("confidence", 0.0)))
        surprise = _clamp(total_error * (0.5 + 0.5 * confidence))
        return {
            "available": True,
            "predicted_state": snapshot.get("predicted_state"),
            "observed_state": str(observed_state),
            "state_observed_probability": round(observed_probability, 6),
            "state_log_loss": round(state_log_loss, 6),
            "state_brier": round(state_brier, 6),
            "success_brier": round(success_brier, 6),
            "verified_brier": round(verified_brier, 6),
            "duration_error": round(duration_error, 6),
            "prediction_error": round(total_error, 6),
            "surprise": round(surprise, 6),
            "confidence": round(confidence, 6),
            "uncertainty": round(_clamp(float(snapshot.get("uncertainty", 1.0))), 6),
            "evidence_count": int(snapshot.get("evidence_count", 0) or 0),
        }

    @staticmethod
    def _no_prediction(*, transition_id: str, state_signature: str,
                       action_signature: str, observed_state: str) -> PredictionError:
        return PredictionError(
            transition_id=transition_id,
            state_signature=state_signature,
            action_signature=action_signature,
            predicted_state=None,
            observed_state=observed_state,
            top_state_probability=0.0,
            top_state_hit=False,
            state_observed_probability=0.0,
            state_log_loss=0.0,
            state_brier=0.0,
            predicted_success_probability=0.0,
            observed_success=False,
            success_brier=0.0,
            predicted_verified_probability=0.0,
            observed_verified=False,
            verified_brier=0.0,
            outcome_log_loss=0.0,
            duration_error=0.0,
            reward_error=0.0,
            value_error=None,
            total_error=0.0,
            surprise=0.0,
            confidence=0.0,
            uncertainty=1.0,
            evidence_count=0,
            prediction_available=False,
            created_at=_now(),
        )

    def annotate_episode(self, transitions: Iterable[dict[str, Any]]) -> tuple[tuple[dict[str, Any], ...], PredictionLearningResult]:
        items = [dict(item) for item in transitions if isinstance(item, dict)]
        scored = 0
        inserted = 0
        errors: list[float] = []
        surprises: list[float] = []
        high = 0
        result_items: list[dict[str, Any]] = []
        for transition in items:
            state = str(transition.get("state_before") or "")
            action = transition.get("action") or {}
            prediction = None
            try:
                if state and isinstance(action, dict):
                    prediction = self.transition_model.predict(state, action)
            except Exception:
                prediction = None
            transition_id = str(transition.get("transition_id") or "")
            if not transition_id:
                transition_id = hashlib.sha256(
                    json.dumps(transition, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
                transition["transition_id"] = transition_id
            error = self.score_prediction(
                prediction, transition, transition_id=transition_id, value_model=self.value_model,
            )
            updated = dict(transition)
            updated["prediction_error"] = error.total_error if error.prediction_available else 0.0
            metadata = list(updated.get("metadata") or ())
            metadata.append(("prediction_error", error.total_error if error.prediction_available else 0.0))
            metadata.append(("prediction_surprise", error.surprise if error.prediction_available else 0.0))
            metadata.append(("prediction_available", error.prediction_available))
            if error.prediction_available:
                metadata.append(("prediction_error_components", {
                    "state_log_loss": error.state_log_loss,
                    "state_brier": error.state_brier,
                    "success_brier": error.success_brier,
                    "verified_brier": error.verified_brier,
                    "outcome_log_loss": error.outcome_log_loss,
                    "duration_error": error.duration_error,
                    "reward_error": error.reward_error,
                    "value_error": error.value_error,
                }))
                metadata.append(("prediction_evidence_count", error.evidence_count))
                metadata.append(("prediction_confidence_before", error.confidence))
            updated["metadata"] = tuple(metadata)
            result_items.append(updated)
            if not error.prediction_available:
                continue
            scored += 1
            errors.append(error.total_error)
            surprises.append(error.surprise)
            high += int(error.total_error >= 0.75)
            inserted += int(self.store.record_prediction_error(error.to_dict()))
        result = PredictionLearningResult(
            transitions=len(items),
            scored_predictions=scored,
            new_error_records=inserted,
            mean_error=round(sum(errors) / max(1, len(errors)), 6),
            mean_surprise=round(sum(surprises) / max(1, len(surprises)), 6),
            high_error_events=high,
        )
        return tuple(result_items), result

    def calibration(self, *, limit: int = 5000, bins: int = 10) -> dict[str, Any]:
        records = self.store.prediction_calibration_records(limit=limit)
        return {
            "sample_count": len(records),
            "bins": self._calibration_for(records, "predicted_success_probability", "observed_success", bins),
            "verified": self._calibration_for(records, "predicted_verified_probability", "observed_verified", bins),
            "next_state": self._calibration_for(records, "top_state_probability", "top_state_hit", bins),
        }

    @staticmethod
    def _calibration_for(records: list[dict], prediction_key: str, observation_key: str, bins: int) -> dict[str, Any]:
        bins = max(1, int(bins))
        groups: list[list[dict]] = [[] for _ in range(bins)]
        for record in records:
            probability = _clamp(float(record.get(prediction_key, 0.0)))
            index = min(bins - 1, int(probability * bins))
            groups[index].append(record)
        out = []
        total = len(records) or 1
        ece = 0.0
        for index, group in enumerate(groups):
            if not group:
                out.append({"bin": index, "count": 0, "mean_prediction": 0.0, "empirical_rate": 0.0, "gap": 0.0})
                continue
            mean_prediction = sum(_clamp(float(x.get(prediction_key, 0.0))) for x in group) / len(group)
            empirical_rate = sum(int(bool(x.get(observation_key))) for x in group) / len(group)
            gap = abs(mean_prediction - empirical_rate)
            ece += (len(group) / total) * gap
            out.append({"bin": index, "count": len(group), "mean_prediction": round(mean_prediction, 6),
                        "empirical_rate": round(empirical_rate, 6), "gap": round(gap, 6)})
        return {"ece": round(_clamp(ece), 6), "reliability": out}

    def stats(self) -> dict[str, Any]:
        return self.store.prediction_error_stats()

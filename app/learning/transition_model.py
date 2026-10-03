from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Iterable


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _normalize_parameters(parameters: Any) -> dict[str, Any]:
    if isinstance(parameters, dict):
        return {str(k): v for k, v in parameters.items()}
    if isinstance(parameters, (list, tuple)):
        normalized = {}
        for item in parameters:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                normalized[str(item[0])] = item[1]
        return normalized
    return {}


def action_signature(action: dict[str, Any] | None) -> str:
    """Stable ActionSpec-equivalent signature; excludes runtime identity/statistics.

    Runtime records may serialize parameters as either a dict or a list of key/value pairs;
    both forms are normalized to the same semantic representation before hashing.
    """
    action = action or {}
    normalized = {
        "capability": action.get("capability", ""),
        "tool": action.get("tool", ""),
        "parameters": _normalize_parameters(action.get("parameters", {})),
        "preconditions": sorted(action.get("preconditions", ()) or ()),
        "expected_effects": sorted(action.get("expected_effects", ()) or ()),
        "risk": action.get("risk", "low"),
        "reversible": bool(action.get("reversible", True)),
    }
    return hashlib.sha256(_json(normalized).encode("utf-8")).hexdigest()


def model_key(state_signature: str, action: dict[str, Any] | None) -> tuple[str, str]:
    return str(state_signature or ""), action_signature(action)


@dataclass(frozen=True)
class TransitionPrediction:
    state_signature: str
    action_signature: str
    predicted_state: str | None
    next_state_probability: float
    success_probability: float
    verified_probability: float
    expected_duration_seconds: float
    predicted_cost: float | None
    predicted_reward: float | None
    confidence: float
    uncertainty: float
    evidence_count: int
    next_state_distribution: tuple[tuple[str, float], ...] = ()
    outcome_distribution: tuple[tuple[str, float], ...] = ()
    failure_distribution: tuple[tuple[str, float], ...] = ()
    stale: bool = False
    source: str = "learned-transition-model"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LearnedTransitionModel:
    """Empirical, persistent transition model.

    The model deliberately uses exact canonical state/action keys. It therefore learns
    contextual dynamics without pretending that incompatible states are interchangeable.
    Observations are aggregated into distributions rather than overwritten by the latest
    run. It predicts only from evidence already observed in the real environment.
    """

    def __init__(self, store, *, prior_strength: float = 2.0):
        self.store = store
        self.prior_strength = max(0.1, float(prior_strength))

    @staticmethod
    def _outcome_key(transition: dict[str, Any]) -> str:
        outcome = transition.get("outcome") or {}
        if not isinstance(outcome, dict):
            outcome = {"value": str(outcome)}
        return "|".join((
            "ok=" + str(bool(outcome.get("ok", transition.get("verified") is True))).lower(),
            "verified=" + str(bool(outcome.get("verified", transition.get("verified") is False))).lower(),
            "failure=" + str(transition.get("failure_class") or ""),
        ))

    @staticmethod
    def _failure_key(transition: dict[str, Any]) -> str | None:
        failure = str(transition.get("failure_class") or "").strip()
        if failure:
            return failure
        outcome = transition.get("outcome") or {}
        if isinstance(outcome, dict) and not bool(outcome.get("ok", True)):
            error = str(outcome.get("error") or "execution_failure").strip()
            return error[:120] or "execution_failure"
        return None

    def learn_transition(self, transition: dict[str, Any]) -> bool:
        if not isinstance(transition, dict):
            return False
        state = str(transition.get("state_before") or "").strip()
        action = transition.get("action")
        next_state = str(transition.get("state_after") or "").strip()
        if not state or not isinstance(action, dict) or not next_state:
            # A transition without a state target cannot teach dynamics. Keep it in replay,
            # but do not fabricate a next state from outcome text.
            return False
        state_sig, action_sig = model_key(state, action)
        duration = float(((transition.get("outcome") or {}).get("duration_ms", 0.0)) or 0.0) / 1000.0
        ok = bool(((transition.get("outcome") or {}).get("ok", transition.get("verified") is True)))
        verified = bool(transition.get("verified"))
        reward = transition.get("reward")
        reward_value = float(reward) if isinstance(reward, (int, float)) else None
        failure = self._failure_key(transition)
        outcome_key = self._outcome_key(transition)
        self.store.upsert_transition_observation(
            state_signature=state_sig,
            action_signature=action_sig,
            action=action,
            next_state=next_state,
            outcome_key=outcome_key,
            failure_key=failure,
            ok=ok,
            verified=verified,
            duration_seconds=max(0.0, duration),
            reward=reward_value,
            observed_at=str(transition.get("timestamp") or _now()),
            transition_id=str(transition.get("transition_id") or "") or None,
        )
        return True

    def learn_episode(self, transitions: Iterable[dict[str, Any]]) -> int:
        learned = 0
        for transition in transitions:
            learned += int(self.learn_transition(transition))
        return learned

    def predict(self, state_signature: str, action: dict[str, Any]) -> TransitionPrediction | None:
        state_sig, action_sig = model_key(state_signature, action)
        row = self.store.get_transition_model(state_sig, action_sig)
        if row is None or int(row.get("observation_count", 0)) <= 0:
            return None

        n = int(row["observation_count"])
        next_states = dict(row.get("next_states") or {})
        outcomes = dict(row.get("outcomes") or {})
        failures = dict(row.get("failures") or {})
        best_state, best_count = (None, 0)
        if next_states:
            best_state, best_count = max(next_states.items(), key=lambda item: (float(item[1]), item[0]))
        total_next = max(1.0, sum(float(v) for v in next_states.values()))
        # Dirichlet-style smoothing prevents one observation from becoming certainty.
        state_cardinality = max(1, len(next_states))
        prior_each = self.prior_strength / state_cardinality
        smoothed = {str(key): (float(value) + prior_each) / (total_next + self.prior_strength)
                    for key, value in next_states.items()}
        state_prob = (float(best_count) + prior_each) / (total_next + self.prior_strength)

        success_count = int(row.get("success_count", 0))
        verified_count = int(row.get("verified_count", 0))
        baseline_n = min(n, int(row.get("regime_baseline_observations", 0) or 0))
        baseline_success = min(success_count, int(row.get("regime_baseline_successes", 0) or 0))
        baseline_verified = min(verified_count, int(row.get("regime_baseline_verified", 0) or 0))
        fresh_n = max(0, n - baseline_n) if baseline_n else n
        fresh_success = max(0, success_count - baseline_success) if baseline_n else success_count
        fresh_verified = max(0, verified_count - baseline_verified) if baseline_n else verified_count
        historical_weight = 0.10 if baseline_n else 1.0
        effective_n = fresh_n + historical_weight * baseline_n
        effective_success = fresh_success + historical_weight * baseline_success
        effective_verified = fresh_verified + historical_weight * baseline_verified
        success_probability = (effective_success + 1.0) / (effective_n + 2.0)
        verified_probability = (effective_verified + 1.0) / (effective_n + 2.0)
        confidence_evidence = effective_n / (effective_n + 5.0)
        base_confidence = _clamp(max(state_prob, success_probability) * confidence_evidence)
        # Phase 5 feedback: systematic historical prediction error reduces future confidence.
        # This is deliberately bounded so early evidence cannot make the model disappear.
        mean_error = _clamp(float(row.get("prediction_error_mean", 0.0)))
        fit_factor = max(0.25, 1.0 - 0.75 * mean_error)
        confidence = _clamp(base_confidence * fit_factor)
        stale = bool(row.get("stale", 0))
        if stale:
            confidence = _clamp(confidence * 0.45)
        uncertainty = _clamp(1.0 - confidence)

        next_state_distribution = tuple(sorted(smoothed.items(), key=lambda item: (-item[1], item[0])))
        outcome_distribution = tuple(sorted(
            ((str(k), float(v) / max(1, sum(float(x) for x in outcomes.values()))) for k, v in outcomes.items()),
            key=lambda item: (-item[1], item[0]),
        ))
        failure_distribution = tuple(sorted(
            ((str(k), float(v) / max(1, sum(float(x) for x in failures.values()))) for k, v in failures.items()),
            key=lambda item: (-item[1], item[0]),
        ))

        return TransitionPrediction(
            state_signature=state_sig,
            action_signature=action_sig,
            predicted_state=best_state,
            next_state_probability=_clamp(state_prob),
            success_probability=_clamp(success_probability),
            verified_probability=_clamp(verified_probability),
            expected_duration_seconds=max(0.0, float(row.get("duration_mean", 0.0))),
            predicted_cost=None,
            predicted_reward=(float(row["reward_mean"]) if row.get("reward_count", 0) else None),
            confidence=confidence,
            uncertainty=uncertainty,
            evidence_count=n,
            next_state_distribution=next_state_distribution,
            outcome_distribution=outcome_distribution,
            failure_distribution=failure_distribution,
            stale=stale,
        )

    def actions_for_state(self, state_signature: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """List the empirically observed actions for an exact learned state context."""
        return self.store.actions_for_state(str(state_signature or ""), limit=limit)

    def inspect(self, state_signature: str, action: dict[str, Any]) -> dict[str, Any] | None:
        state_sig, action_sig = model_key(state_signature, action)
        return self.store.get_transition_model(state_sig, action_sig)

    def stats(self) -> dict[str, Any]:
        return self.store.transition_model_stats()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

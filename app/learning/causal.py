from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .transition_model import action_signature


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rate(items: list[dict[str, Any]]) -> float:
    if not items:
        return 0.0
    return sum(float(bool(item.get("ok"))) for item in items) / len(items)


def _wilson_width(successes: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 1.0
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    radius = z * math.sqrt((p * (1 - p) / total) + (z * z / (4 * total * total))) / denom
    return min(1.0, max(0.0, 2 * radius))


@dataclass(frozen=True)
class CausalEffectEstimate:
    state_signature: str
    treatment_action_signature: str
    control_action_signature: str
    treatment_observations: int
    control_observations: int
    association: float
    controlled_causal_effect: float
    counterfactual_treatment_success: float | None
    counterfactual_control_success: float | None
    counterfactual_effect: float | None
    evidence_confidence: float
    confounding_risk: float
    method: str
    created_at: str

    @property
    def usable(self) -> bool:
        return min(self.treatment_observations, self.control_observations) >= 3 and self.evidence_confidence >= 0.55

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ControlledCausalLearner:
    """Estimate action effects without pretending correlation is causation.

    Observational association is reported separately from the controlled effect. The controlled
    estimate only compares treatment/control actions on the same canonical state signature. The
    counterfactual component uses the learned transition model on that identical state and never
    invokes the runtime or executes a real-world side effect.
    """

    def __init__(self, store, transition_model=None):
        self.store = store
        self.transition_model = transition_model

    def _observations(self, state_signature: str, action_sig: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.store.transition_observations(state_signature, action_sig, limit=limit)
        return rows

    def estimate(self, state_signature: str, treatment_action: dict[str, Any], control_action: dict[str, Any], *,
                 limit: int = 500) -> CausalEffectEstimate:
        state = str(state_signature or "")
        treatment_sig = action_signature(treatment_action)
        control_sig = action_signature(control_action)
        treat = self._observations(state, treatment_sig, limit)
        control = self._observations(state, control_sig, limit)
        global_treat = self.store.transition_observations_for_action(treatment_sig, limit=limit)
        global_control = self.store.transition_observations_for_action(control_sig, limit=limit)
        treat_rate = _rate(treat)
        control_rate = _rate(control)

        # Association is intentionally observational and can be confounded by different state
        # distributions. The causal estimate uses only matched observations from this state.
        association = _rate(global_treat) - _rate(global_control)
        # A controlled estimate is identified only from matched state evidence. Never reuse
        # the pooled observational association here: under Simpson-style confounding they can
        # point in opposite directions.
        controlled_effect = treat_rate - control_rate if treat and control else 0.0

        cf_treat = cf_control = cf_effect = None
        if self.transition_model is not None:
            pred_treat = self.transition_model.predict(state, treatment_action)
            pred_control = self.transition_model.predict(state, control_action)
            if pred_treat is not None and pred_control is not None:
                cf_treat = float(pred_treat.success_probability)
                cf_control = float(pred_control.success_probability)
                cf_effect = cf_treat - cf_control

        minimum_n = min(len(treat), len(control))
        width_t = _wilson_width(sum(int(bool(x.get("ok"))) for x in treat), len(treat))
        width_c = _wilson_width(sum(int(bool(x.get("ok"))) for x in control), len(control))
        evidence_confidence = max(0.0, min(1.0, (minimum_n / (minimum_n + 5.0)) * (1.0 - 0.5 * (width_t + width_c) / 2)))
        confounding_risk = 1.0 if not (treat and control) else abs(association - controlled_effect)
        if global_treat and global_control and treat and control:
            # Large pooled-vs-matched disagreement is direct evidence that state distribution
            # matters; cap the risk to [0,1] rather than inventing a causal adjustment.
            confounding_risk = min(1.0, max(confounding_risk, abs(association - controlled_effect)))
        method = "matched-state-observation"
        if cf_effect is not None:
            method += "+counterfactual-replay"

        return CausalEffectEstimate(
            state_signature=state,
            treatment_action_signature=treatment_sig,
            control_action_signature=control_sig,
            treatment_observations=len(treat),
            control_observations=len(control),
            association=round(association, 6),
            controlled_causal_effect=round(controlled_effect, 6),
            counterfactual_treatment_success=None if cf_treat is None else round(cf_treat, 6),
            counterfactual_control_success=None if cf_control is None else round(cf_control, 6),
            counterfactual_effect=None if cf_effect is None else round(cf_effect, 6),
            evidence_confidence=round(evidence_confidence, 6),
            confounding_risk=round(confounding_risk, 6),
            method=method,
            created_at=_now(),
        )

    def replay_counterfactual(self, state_signature: str, treatment_action: dict[str, Any], control_action: dict[str, Any]) -> dict[str, Any]:
        """Run a bounded model-only counterfactual comparison. No tools, writes, or runtime side effects."""
        if self.transition_model is None:
            return {"available": False, "reason": "missing-transition-model", "side_effects": 0}
        left = self.transition_model.predict(state_signature, treatment_action)
        right = self.transition_model.predict(state_signature, control_action)
        if left is None or right is None:
            return {"available": False, "reason": "missing-model-evidence", "side_effects": 0}
        return {
            "available": True,
            "state_signature": str(state_signature),
            "treatment": {
                "action_signature": left.action_signature,
                "success_probability": left.success_probability,
                "predicted_state": left.predicted_state,
                "predicted_cost": left.predicted_cost,
            },
            "control": {
                "action_signature": right.action_signature,
                "success_probability": right.success_probability,
                "predicted_state": right.predicted_state,
                "predicted_cost": right.predicted_cost,
            },
            "effect": round(left.success_probability - right.success_probability, 6),
            "side_effects": 0,
            "mode": "counterfactual-simulation-only",
        }


__all__ = ["ControlledCausalLearner", "CausalEffectEstimate"]

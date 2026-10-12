from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FailureDiagnosis:
    run_id: str
    failure_class: str
    root_transition_id: str
    root_action_signature: str
    root_state_signature: str
    prediction_error: float
    failure_expected: bool
    alternative_actions: tuple[dict[str, Any], ...]
    avoidable: bool
    confidence: float
    reason: str
    simulation: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryDecision:
    run_id: str
    failure_class: str
    selected_action_signature: str | None
    candidates: tuple[dict[str, Any], ...]
    quality: float
    promoted: bool
    confidence: float
    reason: str
    simulation: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _action_signature(action: dict[str, Any]) -> str:
    from .transition_model import action_signature
    return action_signature(action or {})


class FailureRecoveryLearner:
    """Learns failure causes and safe recovery patterns without executing side effects."""

    def __init__(self, store, transition_model):
        self.store = store
        self.transition_model = transition_model

    def diagnose(self, experience, similar=None) -> FailureDiagnosis | None:
        transitions = [x for x in experience.transitions if isinstance(x, dict)]
        failed = [x for x in transitions if not bool((x.get("outcome") or {}).get("ok", x.get("verified", False)))]
        if not failed:
            return None
        root = failed[0]
        outcome = root.get("outcome") or {}
        failure_class = str(root.get("failure_class") or outcome.get("error") or "execution")[:120]
        error = float(root.get("prediction_error") or 0.0)
        predicted_failure = False
        root_evidence = 0
        root_fit = 0.0
        try:
            model = self.transition_model.inspect(str(root.get("state_before") or ""), root.get("action") or {})
            if model:
                root_evidence = int(model.get("observation_count", 0) or 0)
                mean_error = max(0.0, min(1.0, float(model.get("prediction_error_mean", 0.0) or 0.0)))
                predicted_failure = mean_error >= 0.45 or float(model.get("success_count", 0) or 0) < float(model.get("observation_count", 0) or 0) * 0.5
                root_fit = (root_evidence / (root_evidence + 5.0)) * (1.0 - mean_error)
        except Exception:
            pass
        alternatives=[]
        for exp in list(similar or ())[:20]:
            for t in exp.transitions:
                if not isinstance(t, dict) or not t.get("action"):
                    continue
                if str(t.get("state_before") or "") != str(root.get("state_before") or ""):
                    continue
                action=t.get("action") or {}
                if _action_signature(action)==_action_signature(root.get("action") or {}):
                    continue
                ok=bool((t.get("outcome") or {}).get("ok", t.get("verified", False)))
                if ok:
                    alternatives.append({"action": action, "source_run_id": exp.run_id, "success": True, "cost": float((action or {}).get("cost", 1.0) or 1.0)})
        try:
            learned_alternatives = self.transition_model.actions_for_state(str(root.get("state_before") or ""), limit=20)
        except Exception:
            learned_alternatives = []
        for item in learned_alternatives:
            action = item.get("action") or {}
            if _action_signature(action) == _action_signature(root.get("action") or {}):
                continue
            verified_count = int(item.get("verified_count", 0) or 0)
            success_count = int(item.get("success_count", 0) or 0)
            if verified_count <= 0 and success_count <= 0:
                continue
            alternatives.append({"action": action, "source_run_id": "transition-model", "success": True,
                                 "cost": float((action or {}).get("cost", 1.0) or 1.0),
                                 "evidence_count": int(item.get("observation_count", 0) or 0),
                                 "verified_count": verified_count})
        unique={_action_signature(x["action"]):x for x in alternatives}
        alternatives=list(unique.values())[:8]
        avoidable=bool(alternatives)
        alternative_evidence = sum(max(1, int(x.get("verified_count") or 0), int(x.get("evidence_count") or 0)) for x in alternatives)
        alternative_fit = alternative_evidence / (alternative_evidence + 3.0) if alternative_evidence else 0.0
        conf = math.sqrt(max(0.0, root_fit) * max(0.0, alternative_fit)) if avoidable else root_fit
        return FailureDiagnosis(
            experience.run_id, failure_class, str(root.get("transition_id") or ""),
            _action_signature(root.get("action") or {}), str(root.get("state_before") or ""), error, predicted_failure,
            tuple(alternatives), avoidable, conf,
            "historical successful alternative found" if alternatives else "no verified alternative found",
        )

    def simulate_recovery(self, diagnosis: FailureDiagnosis, action: dict[str, Any]) -> dict[str, Any]:
        """Run a model-only recovery simulation; it never invokes the runtime/tool registry."""
        try:
            prediction = self.transition_model.predict(diagnosis.root_state_signature, action)
        except Exception:
            prediction = None
        success = float(prediction.success_probability) if prediction else 0.5
        uncertainty = float(prediction.uncertainty) if prediction else 1.0
        model_confidence = float(prediction.confidence) if prediction else 0.0
        evidence_count = int(prediction.evidence_count) if prediction else 0
        cost = max(0.1, float(action.get("cost", 1.0) or 1.0))
        score = 0.68 * success + 0.22 * (1.0 - uncertainty) + 0.10 * (1.0 / min(10.0, cost))
        return {
            "action_signature": _action_signature(action),
            "predicted_success_probability": success,
            "predicted_uncertainty": uncertainty,
            "predicted_cost": cost,
            "score": score,
            "model_confidence": max(0.0, min(1.0, model_confidence)),
            "evidence_count": evidence_count,
            "side_effects": 0,
            "simulation_only": True,
            "model_version": int(getattr(prediction, "evidence_count", 0) or 0),
        }

    def choose_recovery(self, diagnosis: FailureDiagnosis) -> RecoveryDecision:
        candidates=[]
        simulations=[]
        for item in diagnosis.alternative_actions:
            action=item["action"]
            simulation=self.simulate_recovery(diagnosis, action)
            simulations.append(simulation)
            candidates.append({
                "action_signature": simulation["action_signature"], "action": action,
                "score": simulation["score"],
                "success_probability": simulation["predicted_success_probability"],
                "uncertainty": simulation["predicted_uncertainty"],
                "simulation_only": True, "side_effects": 0,
            })
        candidates.sort(key=lambda x:(-x["score"],x["action_signature"]))
        simulations.sort(key=lambda x:(-x["score"],x["action_signature"]))
        selected=candidates[0] if candidates else None
        quality=float(selected["score"]) if selected else 0.0
        candidate_confidence=float(selected.get("model_confidence", 0.0)) if selected else 0.0
        confidence = (2.0 * diagnosis.confidence * candidate_confidence / (diagnosis.confidence + candidate_confidence)) if diagnosis.confidence > 0 and candidate_confidence > 0 else 0.0
        return RecoveryDecision(
            run_id=diagnosis.run_id, failure_class=diagnosis.failure_class,
            selected_action_signature=selected["action_signature"] if selected else None,
            candidates=tuple(candidates), quality=quality, promoted=False,
            confidence=max(0.0, min(1.0, confidence)),
            reason="best bounded recovery candidate from verified evidence" if selected else "no-recovery-candidate",
            simulation=tuple(simulations),
        )

    def learn(self, diagnosis: FailureDiagnosis, recovery: RecoveryDecision, *, recovery_verified: bool = False, observed_quality: float | None = None) -> dict[str, Any]:
        key_material = "|".join((diagnosis.failure_class, diagnosis.root_state_signature, diagnosis.root_action_signature, recovery.selected_action_signature or ""))
        key="recovery:"+hashlib.sha256(key_material.encode()).hexdigest()[:24]
        result=self.store.upsert_recovery_lesson(
            key=key, failure_class=diagnosis.failure_class, root_transition_id=diagnosis.root_transition_id,
            root_state_signature=diagnosis.root_state_signature,
            root_action_signature=diagnosis.root_action_signature, selected_action_signature=recovery.selected_action_signature or "",
            quality=recovery.quality, confidence=recovery.confidence, verified=recovery_verified,
            run_id=diagnosis.run_id, diagnosis=diagnosis.to_dict(), candidates=list(recovery.candidates),
            observed_quality=observed_quality,
        )
        return {**recovery.to_dict(), "promotion": result, "diagnosis": diagnosis.to_dict()}

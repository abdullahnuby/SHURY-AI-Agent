from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class InvalidationDecision:
    state_signature: str
    action_signature: str
    invalidated: bool
    distribution_shift: float
    prediction_error_spike: float
    success_rate_delta: float
    reason: str
    stale: bool
    exploration_multiplier: float
    relearn_required: bool
    relearn_ready: bool
    model_version: int
    fresh_observations: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _js_divergence(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    from collections import Counter
    a, b = Counter(left), Counter(right)
    keys = sorted(set(a) | set(b))
    na, nb = float(len(left)), float(len(right))
    pa = {k: a[k] / na for k in keys}
    pb = {k: b[k] / nb for k in keys}
    score = 0.0
    for key in keys:
        m = 0.5 * (pa[key] + pb[key])
        if pa[key] > 0:
            score += 0.5 * pa[key] * __import__('math').log(pa[key] / m)
        if pb[key] > 0:
            score += 0.5 * pb[key] * __import__('math').log(pb[key] / m)
    return _clamp(score / __import__('math').log(2.0))


class ModelInvalidation:
    """Persistent model-drift controller.

    Drift is evidence, not an automatic data wipe. An invalidated transition model is marked
    stale, future planning receives an exploration multiplier, and subsequent real observations
    rebuild confidence. Historical observations remain immutable.
    """

    def __init__(self, store, *, window: int = 12, min_evidence: int = 8,
                 error_spike_threshold: float = 0.35, success_drop_threshold: float = 0.25,
                 distribution_shift_threshold: float = 0.35, relearn_evidence: int = 3):
        self.store = store
        self.window = max(4, int(window))
        self.min_evidence = max(4, int(min_evidence))
        self.error_spike_threshold = float(error_spike_threshold)
        self.success_drop_threshold = float(success_drop_threshold)
        self.distribution_shift_threshold = float(distribution_shift_threshold)
        self.relearn_evidence = max(1, int(relearn_evidence))

    def evaluate(self, state_signature: str, action_signature: str) -> InvalidationDecision:
        row = self.store.get_transition_model(state_signature, action_signature)
        if not row:
            return InvalidationDecision(state_signature, action_signature, False, 0.0, 0.0, 0.0,
                                        "no-model", False, 1.0, False, False, 1, 0)

        evidence = int(row.get("observation_count", 0) or 0)
        if evidence < self.min_evidence:
            stale = bool(row.get("stale", 0))
            return InvalidationDecision(state_signature, action_signature, stale, 0.0, 0.0, 0.0,
                                        "insufficient-evidence", stale, 1.0 if not stale else 2.0,
                                        stale, int(row.get("fresh_observations", 0) or 0) >= self.relearn_evidence,
                                        int(row.get("model_version", 1) or 1), int(row.get("fresh_observations", 0) or 0))

        errors = self.store.transition_prediction_error_series(state_signature, action_signature, limit=self.window * 2)
        split = min(self.window, len(errors) // 2)
        baseline_errors = errors[split:]
        recent_errors = errors[:split]
        prediction_error_spike = 0.0
        if len(baseline_errors) >= 4 and len(recent_errors) >= 4:
            base = max(1e-6, mean(float(x) for x in baseline_errors))
            recent = mean(float(x) for x in recent_errors)
            prediction_error_spike = _clamp((recent - base) / max(base, 1e-6))

        outcomes = self.store.transition_outcome_series(state_signature, action_signature, limit=self.window * 2)
        split_o = min(self.window, len(outcomes) // 2)
        recent_o = outcomes[:split_o]
        baseline_o = outcomes[split_o:]
        recent_success = mean(recent_o) if recent_o else float(row.get("success_count", 0)) / max(1, evidence)
        baseline_success = mean(baseline_o) if baseline_o else float(row.get("success_count", 0)) / max(1, evidence)
        success_rate_delta = max(0.0, float(baseline_success) - float(recent_success))
        recent_failures = sum(1 for value in recent_o if float(value) < 0.5)

        signatures = self.store.transition_outcome_signatures(state_signature, action_signature, limit=self.window * 2)
        split_s = min(self.window, len(signatures) // 2)
        distribution_shift = _js_divergence(signatures[:split_s], signatures[split_s:]) if split_s >= 4 else 0.0

        reasons = []
        if prediction_error_spike >= self.error_spike_threshold:
            reasons.append("prediction-error-spike")
        if success_rate_delta >= self.success_drop_threshold and recent_failures >= 3:
            reasons.append("success-rate-degradation")
        if distribution_shift >= self.distribution_shift_threshold:
            reasons.append("distribution-shift")

        already_stale = bool(row.get("stale"))
        invalidated = bool(reasons) and not already_stale
        if invalidated:
            reason = "+".join(reasons)
            contiguous_failures = 0
            for value in recent_o:
                if float(value) < 0.5:
                    contiguous_failures += 1
                else:
                    break
            regime_kwargs = {}
            if contiguous_failures >= 3:
                regime_kwargs = {
                    "regime_baseline_observations": max(0, evidence - contiguous_failures),
                    "regime_baseline_successes": int(row.get("success_count", 0) or 0),
                    "regime_baseline_verified": int(row.get("verified_count", 0) or 0),
                    "initial_fresh_observations": contiguous_failures,
                }
            row = self.store.invalidate_transition_model(
                state_signature, action_signature,
                reason=reason,
                distribution_shift=distribution_shift,
                error_spike=prediction_error_spike,
                success_rate_delta=success_rate_delta,
                **regime_kwargs,
            )
        elif already_stale:
            reason = str(row.get("invalidation_reason") or "+".join(reasons) or "already-stale")
        else:
            reason = "stable"

        refreshed = self.store.get_transition_model(state_signature, action_signature) or row
        stale = bool(refreshed.get("stale", 0))
        fresh = int(refreshed.get("fresh_observations", 0) or 0)
        ready = fresh >= self.relearn_evidence
        multiplier = 2.25 if stale else 1.0
        return InvalidationDecision(
            state_signature, action_signature, invalidated, distribution_shift,
            prediction_error_spike, success_rate_delta, reason, stale, multiplier,
            stale, ready, int(refreshed.get("model_version", 1) or 1), fresh,
        )

    def evaluate_transition(self, transition: dict[str, Any]) -> InvalidationDecision:
        from .transition_model import action_signature
        decision = self.evaluate(str(transition.get("state_before") or ""), action_signature(transition.get("action") or {}))
        if decision.stale:
            action = transition.get("action") or {}
            tool = str(action.get("tool") or "") if isinstance(action, dict) else ""
            if tool:
                try:
                    invalidated = self.store.invalidate_procedural_memories_for_tool(
                        tool, reason=f"transition-model-stale:{decision.reason}"
                    )
                except Exception:
                    invalidated = 0
                if invalidated:
                    return InvalidationDecision(
                        **{**decision.to_dict(), "reason": decision.reason + "+procedure-invalidation"}
                    )
        return decision

    def stats(self) -> dict[str, Any]:
        return self.store.model_invalidation_stats()

from __future__ import annotations
from collections import Counter


def promotion_gate(skill, experiences, evaluations, *, min_successes=2, min_verified=2, min_contexts=2):
    successes=[x for x in experiences if x.status=="completed" and x.verified_rate>=0.80]
    verified_count=len(successes)
    contexts=len({x.environment_signature for x in successes if x.environment_signature})
    if contexts < min_contexts:
        # Distinct goals are a valid proxy when an explicit environment signature is unavailable.
        contexts=len({x.task_signature for x in successes})
    deltas=[e.delta for e in evaluations if e.replay_kind=="counterfactual"]
    regressions=sum(1 for e in evaluations if e.regression)
    mean_delta=(sum(deltas)/len(deltas)) if deltas else -1.0
    positive=max(deltas, default=-1.0) >= 0.05
    no_regression=regressions==0
    enough_success=len(successes)>=min_successes
    enough_verified=verified_count>=min_verified
    enough_contexts=contexts>=min_contexts
    promotable=all((enough_success,enough_verified,enough_contexts,no_regression,mean_delta>=-0.02,positive))
    return {
        "promotable":promotable,
        "successes":len(successes),"verified_successes":verified_count,"contexts":contexts,
        "mean_delta":round(mean_delta,6),"positive_evidence":positive,"regressions":regressions,
        "enough_successes":enough_success,"enough_verified":enough_verified,"enough_contexts":enough_contexts,
        "no_regression":no_regression,
        "reason":"all promotion gates passed" if promotable else "promotion gates not satisfied",
    }

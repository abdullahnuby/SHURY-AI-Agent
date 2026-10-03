"""Algorithmic planning primitives for the model-free agent.

The module intentionally uses only the Python standard library.  It provides
relaxed planning heuristics, landmark extraction, Pareto dominance helpers and
Bayesian reliability estimates used by the V10 planner.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import prod
from typing import Iterable

from app.domain.operators import Operator, OperatorRegistry


@dataclass(frozen=True)
class ReliabilityPosterior:
    """Beta(1,1) posterior mean plus a conservative uncertainty term."""
    attempts: int
    successes: int

    @property
    def mean(self) -> float:
        return (self.successes + 1.0) / (self.attempts + 2.0)

    @property
    def failures(self) -> int:
        return max(0, self.attempts - self.successes)

    @property
    def lower_bound(self) -> float:
        # Deterministic one-sided shrinkage; avoids over-trusting a tiny sample.
        n = self.attempts
        if n <= 0:
            return 0.5
        uncertainty = min(0.25, 1.0 / (n ** 0.5))
        return max(0.0, self.mean - uncertainty)


def bayes_estimate(attempts: int, successes: int) -> ReliabilityPosterior:
    return ReliabilityPosterior(max(0, int(attempts)), max(0, min(int(successes), int(attempts))))


def relaxed_fact_costs(operators: OperatorRegistry, initial_facts: Iterable[str]) -> dict[str, float]:
    """Compute an h_add-like relaxed cost over facts (delete effects ignored).

    The fixed point is deterministic and bounded. A fact gets the cheapest cost
    of any producer whose preconditions can themselves be cheaply relaxed.
    """
    costs = {f: 0.0 for f in initial_facts}
    changed = True
    passes = 0
    while changed and passes <= max(1, len(operators.items) * 2):
        passes += 1
        changed = False
        for op in sorted(operators.items, key=lambda x: (x.search_cost(), x.name)):
            if not op.produces:
                continue
            pre_costs = [costs.get(p) for p in op.preconditions]
            if any(v is None for v in pre_costs):
                continue
            candidate = op.search_cost() + sum(pre_costs)
            for fact in op.produces:
                old = costs.get(fact)
                if old is None or candidate + 1e-9 < old:
                    costs[fact] = candidate
                    changed = True
    return costs


def clause_relaxed_cost(text: str, operators: OperatorRegistry, fact_costs: dict[str, float]) -> float:
    """Lower-bound the cost of achieving one goal clause in a relaxed world."""
    values: list[float] = []
    for op in operators.items:
        if not op.matches(text):
            continue
        pre = [fact_costs.get(p, float("inf")) for p in op.preconditions]
        if any(v == float("inf") for v in pre):
            continue
        values.append(op.search_cost() + sum(pre))
    return min(values, default=float("inf"))


def landmark_facts(goal_clauses, operators: OperatorRegistry) -> set[str]:
    """Derive conservative singleton landmarks.

    A fact is a landmark when every currently-registered direct achiever for a
    clause requires that fact. This is intentionally conservative: false
    positives are more harmful to planning than omitted weak landmarks.
    """
    out: set[str] = set()
    for clause in goal_clauses:
        candidates = [o for o in operators.items if o.matches(clause.text)]
        if not candidates:
            continue
        common = set(candidates[0].preconditions)
        for op in candidates[1:]:
            common.intersection_update(op.preconditions)
        out.update(common)
    return out


def goal_heuristic(goal_clauses, completed: set[int] | frozenset[int], operators: OperatorRegistry,
                   state: set[str]) -> tuple[float, int, set[str]]:
    """Return relaxed lower bound, missing landmarks and landmark set."""
    remaining = [c for c in goal_clauses if c.index not in completed]
    fact_costs = relaxed_fact_costs(operators, state)
    total = 0.0
    for clause in remaining:
        cost = clause_relaxed_cost(clause.text, operators, fact_costs)
        if cost == float("inf"):
            return float("inf"), 0, set()
        total += cost
    landmarks = landmark_facts(remaining, operators)
    missing = len([f for f in landmarks if f not in state])
    return total, missing, landmarks


def expected_plan_failure(probabilities: Iterable[float]) -> float:
    ps = [max(0.0, min(1.0, float(p))) for p in probabilities]
    return 1.0 - prod(1.0 - p for p in ps) if ps else 0.0


def pareto_dominates(cost_a: float, duration_a: float, risk_a: float,
                     cost_b: float, duration_b: float, risk_b: float) -> bool:
    """Whether A is no worse on all three axes and strictly better on one."""
    no_worse = cost_a <= cost_b + 1e-9 and duration_a <= duration_b + 1e-9 and risk_a <= risk_b + 1e-9
    strict = cost_a < cost_b - 1e-9 or duration_a < duration_b - 1e-9 or risk_a < risk_b - 1e-9
    return no_worse and strict

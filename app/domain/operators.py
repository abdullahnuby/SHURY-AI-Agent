"""Typed deterministic operators and state-transition metadata."""
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Operator:
    name: str
    tool: str
    capability: str
    cost: float = 1.0
    duration: float = 0.0
    reliability: float = 1.0
    risk_penalty: float = 0.0
    preconditions: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    removes: tuple[str, ...] = ()
    resource_costs: tuple[tuple[str, float], ...] = ()
    resources_required: tuple[str, ...] = ()
    exclusive_resources: tuple[str, ...] = ()
    verification_level: str = "standard"
    matcher: Callable[[str], bool] | None = None
    parallel_safe: bool = False
    idempotent: bool = True
    intent_priority: int = 0

    def matches(self, goal: str) -> bool:
        return bool(self.matcher and self.matcher(goal))

    def applicable(self, state: set[str], resources: dict[str, float] | None = None) -> bool:
        if not set(self.preconditions).issubset(state):
            return False
        resources = resources or {}
        if any(r not in resources for r in self.resources_required):
            return False
        return all(resources.get(k, 0.0) >= v for k, v in self.resource_costs)

    def search_cost(self) -> float:
        # Risk-adjusted expected effort. Reliability is supplied by the local
        # experience store; no stochastic model is required.
        failure_penalty = max(0.0, 1.0 - self.reliability) * 5.0
        # Explicit intent priority is a planning utility, not a claim about truth.
        # It lets highly specific capabilities (e.g. web research) beat a cheaper
        # generic matcher (e.g. note search) when both match the same phrase.
        return self.cost + self.risk_penalty + failure_penalty - 0.75 * self.intent_priority

    def duration_cost(self) -> float:
        return max(0.0, self.duration)


@dataclass
class OperatorRegistry:
    items: list[Operator] = field(default_factory=list)

    def candidates(self, goal: str, state: set[str] | None = None,
                   resources: dict[str, float] | None = None,
                   include_support: bool = False) -> list[Operator]:
        state = state or set()
        candidates = [x for x in self.items if x.matches(goal) and x.applicable(state, resources)]
        return sorted(candidates, key=lambda x: (-x.intent_priority, x.search_cost(), x.duration_cost(), x.risk_penalty, x.name))

    def producers(self, fact: str) -> list[Operator]:
        return sorted((x for x in self.items if fact in x.produces),
                      key=lambda x: (x.search_cost(), x.duration_cost(), x.name))


def build_operators(registry: dict, reliability: dict[str, float] | None = None) -> OperatorRegistry:
    reliability = reliability or {}
    items = []
    risk_penalty = {"low": 0.0, "medium": 1.0, "high": 3.0}
    for t in registry.values():
        items.append(Operator(
            name=t.name,
            tool=t.name,
            capability=t.capability or t.name,
            cost=t.cost + t.stage * .25,
            duration=t.duration,
            reliability=reliability.get(t.name, 1.0),
            risk_penalty=risk_penalty.get(t.risk, 1.0),
            preconditions=t.preconditions,
            produces=t.produces,
            removes=t.removes,
            resource_costs=t.resource_costs,
            resources_required=t.resources_required,
            exclusive_resources=t.exclusive_resources,
            verification_level=t.verification_level,
            matcher=t.matches,
            parallel_safe=t.parallel_safe,
            idempotent=t.idempotent,
            intent_priority=t.intent_priority,
        ))
    return OperatorRegistry(items)

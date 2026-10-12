from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

STRATEGIES = (
    "direct",
    "sequential",
    "search",
    "exploration",
    "verification-first",
    "information-first",
    "recovery-first",
)


@dataclass(frozen=True)
class StrategyDecision:
    state_type: str
    preferred_strategy: str
    score: float
    evidence_count: int
    alternatives: tuple[dict[str, Any], ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetaStrategyController:
    """Persistent controller over planning strategies.

    The controller learns which *strategy family* works for a state type. It does not choose
    concrete tools, bypass validation, or execute anything; it only orders already-governed
    planning routes.
    """

    def __init__(self, store, *, exploration: float = 0.20):
        self.store = store
        self.exploration = max(0.0, float(exploration))

    @staticmethod
    def _state_type(state: Any) -> str:
        if isinstance(state, str):
            return state.strip() or "unknown"
        if isinstance(state, dict):
            return str(state.get("state_type") or state.get("type") or "unknown").strip() or "unknown"
        return "unknown"

    def _score(self, state_type: str, strategy: str) -> dict[str, Any]:
        row = self.store.meta_strategy_observation(state_type, strategy)
        n = int(row.get("attempts", 0) or 0)
        mean_reward = float(row.get("reward_mean", 0.0) or 0.0)
        success = float(row.get("success_rate", 0.0) or 0.0)
        n_eff = max(1.0, float(n))
        ucb = mean_reward + self.exploration * math.sqrt(math.log(n_eff + 2.0) / n_eff)
        return {"strategy": strategy, "attempts": n, "success_rate": success,
                "reward_mean": mean_reward, "ucb": ucb}

    def recommend(self, state_type: str, *, available: Iterable[str] | None = None,
                  context: dict[str, Any] | None = None) -> StrategyDecision:
        state_type = self._state_type(state_type)
        allowed = [str(x) for x in (available or STRATEGIES) if str(x) in STRATEGIES]
        if not allowed:
            allowed = list(STRATEGIES)
        scores = [self._score(state_type, strategy) for strategy in allowed]
        scores.sort(key=lambda row: (-float(row["ucb"]), row["strategy"]))
        top = scores[0]
        seen = sum(int(x["attempts"]) for x in scores)
        reason = "learned state-type strategy preference" if int(top["attempts"]) else "cold-start deterministic strategy prior"
        return StrategyDecision(state_type, top["strategy"], float(top["ucb"]), seen,
                                tuple(scores), reason)

    def record_outcome(self, *, state_type: str, strategy: str, reward: float,
                       success: bool, context: dict[str, Any] | None = None) -> dict[str, Any]:
        strategy = str(strategy or "").strip()
        if strategy not in STRATEGIES:
            return {"recorded": False, "reason": "unknown-strategy"}
        return self.store.record_meta_strategy_observation(
            self._state_type(state_type), strategy, float(reward), bool(success), metadata=context or {}
        )

    def preferred_table(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return self.store.meta_strategy_preferences(limit=limit)

    def stats(self) -> dict[str, Any]:
        return self.store.meta_strategy_stats()

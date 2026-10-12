from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TransitionBelief:
    state_signature: str
    action_signature: str
    hypothesis_key: str
    evidence_count: int
    supporting_evidence: int
    contradicting_evidence: int
    probability: float
    confidence: float
    first_seen_at: str
    last_seen_at: str
    last_model_version: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContinualBeliefTracker:
    """Inspect competing transition hypotheses without collapsing them into one label."""

    def __init__(self, store):
        self.store = store

    def beliefs(self, state_signature: str, action_signature: str, *, limit: int = 100) -> list[TransitionBelief]:
        return [TransitionBelief(**row) for row in self.store.transition_beliefs(state_signature, action_signature, limit=limit)]

    def history(self, state_signature: str, action_signature: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.transition_model_history(state_signature, action_signature, limit=limit)

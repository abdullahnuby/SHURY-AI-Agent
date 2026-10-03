from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ExperienceRecord:
    """Episode-level experience record kept for backward compatibility.

    ``run_id`` is the durable episode id. ``transitions`` contains serialized
    Phase-1 Transition records when the runtime had enough observed state/action
    evidence to construct them. Older records may legitimately have no transitions.
    """
    run_id: str
    goal: str
    task_signature: str
    status: str
    reward: float
    verified_rate: float
    steps: tuple[dict, ...]
    failure_class: str | None
    lesson_keys: tuple[str, ...]
    session_id: str | None
    created_at: str
    environment_signature: str = ""
    transitions: tuple[dict[str, Any], ...] = ()
    operation: str = ""

    @property
    def episode_id(self) -> str:
        return self.run_id

    @property
    def meaningful(self) -> bool:
        return bool(self.transitions) or any(
            str(step.get("status", "")) in {"done", "failed"}
            for step in self.steps
            if isinstance(step, dict)
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReplayItem:
    """Durable replay index entry for one transition."""
    transition_id: str
    episode_id: str
    transition_index: int
    transition: dict[str, Any]
    priority: float
    prediction_error: float
    novelty: float
    failure_importance: float
    uncertainty: float
    learning_value: float
    boundary: float = 0.0
    contradictory: float = 0.0
    replay_count: int = 0
    created_at: str = ""
    model_version: int = 1
    model_change_recency: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Lesson:
    key: str
    task_signature: str
    kind: str
    lesson: str
    when_to_apply: tuple[str, ...]
    avoid: tuple[str, ...]
    evidence_run_ids: tuple[str, ...]
    confidence: float
    status: str
    uses: int = 0
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProceduralMemory:
    key: str
    task_family_signature: str
    operation: str
    capability: str
    workflow: tuple[dict[str, Any], ...]
    trigger_conditions: tuple[str, ...]
    termination_conditions: tuple[str, ...]
    recovery_strategy: tuple[str, ...]
    context_boundary: tuple[str, ...]
    evidence_run_ids: tuple[str, ...]
    successes: int
    failures: int
    confidence: float
    status: str
    version: int = 1
    created_at: str = ""
    last_used_at: str = ""
    invalidated_at: str = ""
    invalidation_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillEvaluation:
    candidate_key: str
    goal: str
    baseline_reward: float
    candidate_reward: float
    delta: float
    verified: bool
    regression: bool
    replay_kind: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LearningStage:
    """Durable stage result for one real execution learning cycle."""
    run_id: str
    stage: str
    status: str
    started_at: str
    completed_at: str
    payload: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LearningCycleResult:
    """Machine-readable summary of the ordered online learning loop."""
    run_id: str
    status: str
    duplicate: bool
    transitions: int
    stages: tuple[LearningStage, ...] = ()
    policy_updated: bool = False
    self_model_refreshed: bool = False
    language_patterns_updated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "duplicate": self.duplicate,
            "transitions": self.transitions,
            "stages": [stage.to_dict() for stage in self.stages],
            "policy_updated": self.policy_updated,
            "self_model_refreshed": self.self_model_refreshed,
            "language_patterns_updated": self.language_patterns_updated,
        }


@dataclass(frozen=True)
class EvolutionDecision:
    candidate_key: str
    action: str
    reason: str
    gates: dict[str, Any]
    before_status: str
    after_status: str

    def to_dict(self) -> dict:
        return asdict(self)

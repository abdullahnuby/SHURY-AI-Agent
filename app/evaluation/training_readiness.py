from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TrainingGateResult:
    ready_for_external_world: bool
    completed_levels: tuple[int, ...]
    required_levels: tuple[int, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_for_external_world": self.ready_for_external_world,
            "completed_levels": list(self.completed_levels),
            "required_levels": list(self.required_levels),
            "blockers": list(self.blockers),
        }


def evaluate_training_readiness(completed_levels: set[int] | None = None, *,
                                unseen_task_pass_rate: float = 0.0,
                                safety_violations: int = 0) -> TrainingGateResult:
    completed = set(completed_levels or set())
    required = tuple(range(1, 10))
    blockers: list[str] = []
    missing = [x for x in required if x not in completed]
    if missing:
        blockers.append(f"missing_levels:{','.join(map(str, missing))}")
    if unseen_task_pass_rate < 0.90:
        blockers.append("unseen_task_pass_rate_below_0.90")
    if safety_violations != 0:
        blockers.append("safety_violations_present")
    # External-world access remains disabled until deterministic capability evidence is
    # complete. This gate is policy state, not a claim that a model has been trained.
    return TrainingGateResult(
        ready_for_external_world=not blockers,
        completed_levels=tuple(sorted(completed)),
        required_levels=required,
        blockers=tuple(blockers),
    )

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Callable


@dataclass(frozen=True)
class ExpectedOutcome:
    status: str = "completed"
    acceptable_statuses: tuple[str, ...] = ()
    final_contains: tuple[str, ...] = ()
    final_regex: str = ""
    output_contains: tuple[str, ...] = ()
    output_regex: str = ""
    required_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    tool_order: tuple[str, ...] = ()
    max_steps: int | None = None
    max_seconds: float | None = None
    required_world: dict[str, Any] = field(default_factory=dict)
    forbidden_world_changes: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    must_not_ask_user: bool = False
    min_verified_rate: float = 1.0
    min_trajectory_score: float = 0.0


@dataclass(frozen=True)
class EvalScenario:
    id: str
    name: str
    goal: str
    tags: tuple[str, ...] = ()
    difficulty: str = "medium"
    expected: ExpectedOutcome = field(default_factory=ExpectedOutcome)
    repetitions: int = 1
    session_id: str | None = None
    workspace_files: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["expected"] = asdict(self.expected)
        return d


@dataclass
class StepTrace:
    index: int
    step_id: str
    tool: str
    args: dict[str, Any]
    status: str
    verified: bool
    attempts: int
    output: Any = None
    error: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclass
class Trajectory:
    run_id: str
    trace_id: str
    goal: str
    status: str
    final_message: str
    steps: list[StepTrace]
    replans: int = 0
    duration_seconds: float = 0.0
    world_before: dict[str, Any] = field(default_factory=dict)
    world_after: dict[str, Any] = field(default_factory=dict)
    changed_paths: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def verified_rate(self) -> float:
        return sum(1 for s in self.steps if s.verified and s.status == "done") / max(1, sum(1 for s in self.steps if s.status in {"done", "failed"}))


@dataclass
class DimensionScore:
    name: str
    score: float
    weight: float
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureAttribution:
    category: str
    step_id: str | None
    tool: str | None
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioRun:
    scenario_id: str
    repetition: int
    trajectory: Trajectory
    scores: list[DimensionScore]
    total_score: float
    passed: bool
    failure: FailureAttribution | None = None

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "repetition": self.repetition,
            "trajectory": asdict(self.trajectory),
            "scores": [asdict(x) for x in self.scores],
            "total_score": self.total_score,
            "passed": self.passed,
            "failure": asdict(self.failure) if self.failure else None,
        }


@dataclass
class ScenarioAggregate:
    scenario_id: str
    repetitions: int
    pass_count: int
    pass_rate: float
    pass_at_n: float
    all_n: float
    mean_score: float
    p50_score: float
    min_score: float
    max_score: float
    mean_steps: float
    mean_duration_seconds: float
    horizon_survival: dict[int, float]
    failure_patterns: dict[str, int]
    runs: list[ScenarioRun]

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "repetitions": self.repetitions,
            "pass_count": self.pass_count,
            "pass_rate": self.pass_rate,
            "pass_at_n": self.pass_at_n,
            "all_n": self.all_n,
            "mean_score": self.mean_score,
            "p50_score": self.p50_score,
            "min_score": self.min_score,
            "max_score": self.max_score,
            "mean_steps": self.mean_steps,
            "mean_duration_seconds": self.mean_duration_seconds,
            "horizon_survival": self.horizon_survival,
            "failure_patterns": self.failure_patterns,
            "runs": [x.to_dict() for x in self.runs],
        }


@dataclass
class EvaluationReport:
    run_id: str
    version: str
    started_at: str
    ended_at: str
    scenario_count: int
    run_count: int
    pass_count: int
    pass_rate: float
    mean_score: float
    p50_score: float
    safety_violations: int
    regression_blocked: bool
    reproducible: bool
    scenario_results: list[ScenarioAggregate]
    failure_patterns: dict[str, int]
    attribution: list[FailureAttribution]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "version": self.version,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "scenario_count": self.scenario_count,
            "run_count": self.run_count,
            "pass_count": self.pass_count,
            "pass_rate": self.pass_rate,
            "mean_score": self.mean_score,
            "p50_score": self.p50_score,
            "safety_violations": self.safety_violations,
            "regression_blocked": self.regression_blocked,
            "reproducible": self.reproducible,
            "scenario_results": [x.to_dict() for x in self.scenario_results],
            "failure_patterns": self.failure_patterns,
            "attribution": [asdict(x) for x in self.attribution],
            "metadata": self.metadata,
        }


AgentCallable = Callable[[EvalScenario, int], Any]

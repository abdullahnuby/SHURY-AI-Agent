from __future__ import annotations
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable

from app.domain.state import AgentState
from app.knowledge.memory import get_memory
from app.world.store import load_session_world

from .lab_models import (
    EvalScenario,
    EvaluationReport,
    FailureAttribution,
    ScenarioAggregate,
    ScenarioRun,
    StepTrace,
    Trajectory,
)
from .regression import wilson_interval
from .scenarios import default_scenarios
from .scorers import aggregate_scores, horizon_survival, reproducibility, score_trajectory

DEFAULT_DIR = Path("data") / "evaluations"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _path_snapshot(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    import hashlib
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


def _changed_paths(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    keys = set(before) | set(after)
    return tuple(sorted(k for k in keys if before.get(k) != after.get(k)))


def trajectory_from_state(state: AgentState, memory, *, world_before: dict[str, Any] | None = None) -> Trajectory:
    effects = {e["step_id"]: e for e in memory.effects(state.run_id)}
    steps: list[StepTrace] = []
    for i, step in enumerate(state.plan.steps if state.plan else [], 1):
        effect = effects.get(step.id, {})
        steps.append(
            StepTrace(
                index=i,
                step_id=step.id,
                tool=step.tool,
                args=dict(step.args),
                status=step.status,
                verified=bool(effect.get("verified", step.status == "done")),
                attempts=int(step.attempts),
                output=step.output,
                error=step.error or effect.get("error"),
                depends_on=tuple(step.depends_on),
            )
        )
    return Trajectory(
        run_id=state.run_id,
        trace_id=state.trace_id,
        goal=state.goal,
        status=state.status,
        final_message=state.final_message,
        steps=steps,
        replans=int(state.replans),
        duration_seconds=float(getattr(state.world, "elapsed", 0.0)),
        world_before=dict(world_before or {}),
        world_after=state.world.snapshot(),
        changed_paths=(),
        metadata={"planner": state.plan.planner if state.plan else None},
    )


def _default_adapter(scenario: EvalScenario, repetition: int, approve=None):
    from app.runtime.cognitive_agent import run_cognitive
    sid = scenario.session_id or f"eval-{scenario.id}-{repetition}"
    return run_cognitive(
        scenario.goal,
        approve=approve or (lambda *a, **k: True),
        max_steps=scenario.expected.max_steps or 10,
        session_id=sid,
    )


def _scenario_environment(root: Path, scenario: EvalScenario) -> Path:
    workspace = root / f"workspace-{scenario.id.replace('.', '_')}-{uuid.uuid4().hex[:8]}"
    workspace.mkdir(parents=True, exist_ok=True)
    for rel, content in scenario.workspace_files.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return workspace


class EvaluationLab:
    """Local-first, trajectory-level evaluation and release-gating harness."""

    def __init__(self, *, output_dir: str | Path = DEFAULT_DIR, version: str | None = None):
        self.output_dir = Path(output_dir)
        self.version = version or (Path("VERSION").read_text().strip() if Path("VERSION").exists() else "unknown")

    def run(
        self,
        scenarios: list[EvalScenario] | None = None,
        *,
        agent: Callable[[EvalScenario, int], Any] | None = None,
        approve=None,
        repetitions: int | None = None,
    ) -> EvaluationReport:
        scenarios = list(scenarios or default_scenarios())
        agent = agent or (lambda scenario, rep: _default_adapter(scenario, rep, approve=approve))
        started = _now()
        report_id = uuid.uuid4().hex
        scenario_results: list[ScenarioAggregate] = []
        all_runs: list[ScenarioRun] = []
        failures: dict[str, int] = {}
        attributions: list[FailureAttribution] = []
        safety_violations = 0

        work_root = self.output_dir.joinpath("work").resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        original_workspace_env = os.environ.get("AGENT_WORKSPACE")

        try:
            for scenario in scenarios:
                n = repetitions or scenario.repetitions or 1
                runs: list[ScenarioRun] = []
                scenario_failures: dict[str, int] = {}
                shared_session = bool(scenario.metadata.get("shared_session"))
                for rep in range(1, n + 1):
                    workspace = _scenario_environment(work_root, scenario)
                    before_files = _path_snapshot(workspace)
                    os.environ["AGENT_WORKSPACE"] = str(workspace)
                    base_session = scenario.session_id or f"eval-{scenario.id}"
                    session_key = base_session if shared_session else f"{base_session}-{rep}"
                    try:
                        world_before = load_session_world(get_memory(), session_key).snapshot()
                    except Exception:
                        world_before = {}

                    state = agent(scenario, rep)
                    if not isinstance(state, AgentState):
                        raise TypeError("evaluation agent callable must return AgentState")
                    after_files = _path_snapshot(workspace)
                    trajectory = trajectory_from_state(state, get_memory(), world_before=world_before)
                    trajectory.changed_paths = _changed_paths(before_files, after_files)
                    scores, failure = score_trajectory(trajectory, scenario.expected)
                    total_weight = sum(s.weight for s in scores)
                    total = sum(s.score * s.weight for s in scores) / max(total_weight, 1e-9)
                    passed = all(s.passed for s in scores) and total >= scenario.expected.min_trajectory_score
                    run = ScenarioRun(scenario.id, rep, trajectory, scores, total, passed, failure)
                    runs.append(run)
                    all_runs.append(run)
                    if failure:
                        failures[failure.category] = failures.get(failure.category, 0) + 1
                        scenario_failures[failure.category] = scenario_failures.get(failure.category, 0) + 1
                        attributions.append(failure)
                    safety_violations += sum(
                        len(s.details.get("violations", [])) for s in scores if s.name == "safety"
                    )

                values = [r.total_score for r in runs]
                pass_count = sum(1 for r in runs if r.passed)
                aggregate_mean, p50, minimum, maximum = aggregate_scores(values)
                scenario_results.append(
                    ScenarioAggregate(
                        scenario_id=scenario.id,
                        repetitions=len(runs),
                        pass_count=pass_count,
                        pass_rate=pass_count / max(1, len(runs)),
                        pass_at_n=1.0 if pass_count > 0 else 0.0,
                        all_n=1.0 if pass_count == len(runs) else 0.0,
                        mean_score=aggregate_mean,
                        p50_score=p50,
                        min_score=minimum,
                        max_score=maximum,
                        mean_steps=mean(r.trajectory.step_count for r in runs),
                        mean_duration_seconds=mean(r.trajectory.duration_seconds for r in runs),
                        horizon_survival=horizon_survival([r.trajectory for r in runs], max_horizon=10),
                        failure_patterns=scenario_failures,
                        runs=runs,
                    )
                )
        finally:
            if original_workspace_env is None:
                os.environ.pop("AGENT_WORKSPACE", None)
            else:
                os.environ["AGENT_WORKSPACE"] = original_workspace_env

        ended = _now()
        pass_count = sum(1 for r in all_runs if r.passed)
        values = [r.total_score for r in all_runs]
        ci_low, ci_high = wilson_interval(pass_count, len(all_runs))
        reproducible = bool(scenario_results) and all(
            reproducibility([r.total_score for r in result.runs])["reproducible"]
            for result in scenario_results
        )
        report = EvaluationReport(
            run_id=report_id,
            version=self.version,
            started_at=started,
            ended_at=ended,
            scenario_count=len(scenarios),
            run_count=len(all_runs),
            pass_count=pass_count,
            pass_rate=pass_count / max(1, len(all_runs)),
            mean_score=mean(values) if values else 0.0,
            p50_score=median(values) if values else 0.0,
            safety_violations=safety_violations,
            regression_blocked=False,
            reproducible=reproducible,
            scenario_results=scenario_results,
            failure_patterns=failures,
            attribution=attributions,
            metadata={
                "deterministic_scorers": True,
                "judge": "optional_and_calibrated",
                "pass_rate_ci_95": {"low": ci_low, "high": ci_high},
                "pass_at_n_definition": "at least one successful trial",
                "all_n_definition": "every repeated trial passes",
                "session_isolation_default": True,
                "trajectory_level": True,
            },
        )
        self._write_report(report)
        return report

    def compare(
        self,
        baseline: EvaluationReport | dict[str, Any],
        candidate: EvaluationReport | dict[str, Any],
        *,
        max_regression: float = 0.03,
        max_safety_increase: int = 0,
    ) -> dict[str, Any]:
        baseline_dict = baseline.to_dict() if isinstance(baseline, EvaluationReport) else baseline
        candidate_dict = candidate.to_dict() if isinstance(candidate, EvaluationReport) else candidate
        regressions = []
        baseline_map = {x["scenario_id"]: x for x in baseline_dict.get("scenario_results", [])}
        candidate_map = {x["scenario_id"]: x for x in candidate_dict.get("scenario_results", [])}
        for scenario_id, base in baseline_map.items():
            current = candidate_map.get(scenario_id)
            if not current:
                continue
            score_delta = float(current.get("mean_score", 0.0)) - float(base.get("mean_score", 0.0))
            pass_delta = float(current.get("pass_rate", 0.0)) - float(base.get("pass_rate", 0.0))
            if score_delta < -max_regression or pass_delta < -max_regression:
                regressions.append({"scenario_id": scenario_id, "score_delta": score_delta, "pass_rate_delta": pass_delta})
        safety_delta = int(candidate_dict.get("safety_violations", 0)) - int(baseline_dict.get("safety_violations", 0))
        return {
            "blocked": bool(regressions) or safety_delta > max_safety_increase,
            "regressions": regressions,
            "safety_delta": safety_delta,
            "baseline": {"pass_rate": baseline_dict.get("pass_rate", 0.0), "mean_score": baseline_dict.get("mean_score", 0.0)},
            "candidate": {"pass_rate": candidate_dict.get("pass_rate", 0.0), "mean_score": candidate_dict.get("mean_score", 0.0)},
        }

    def save_json(self, report: EvaluationReport, path: str | Path) -> None:
        Path(path).write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_report(self, report: EvaluationReport) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / f"{report.run_id}.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def load_report(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

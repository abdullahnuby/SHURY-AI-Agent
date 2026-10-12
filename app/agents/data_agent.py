from __future__ import annotations

from pathlib import Path
from typing import Any

from app.knowledge.data_analysis import answer_question, profile_dataset

from .base import SpecialistAgent
from .contracts import AgentResult, AgentSpec, AgentTask


class DataAgent(SpecialistAgent):
    """Read-only specialist for dataset profiling and targeted analysis."""

    def __init__(self, agent_id: str = "data-agent"):
        super().__init__(
            AgentSpec(
                agent_id=agent_id,
                name="Data Agent",
                capability="data_analysis",
                description="Profiles datasets and answers bounded analytical questions without writing to the workspace.",
                allowed_tools=("profile_dataset", "analyze_dataset"),
                read_only=True,
                max_timeout_seconds=30.0,
                resource_budget={"disk_io": 1.0, "cpu": 1.0},
            )
        )

    def run(self, task: AgentTask) -> AgentResult:
        path_value = task.inputs.get("path") or task.inputs.get("file_path") or task.inputs.get("dataset")
        if not path_value:
            return AgentResult(
                task_id=task.task_id,
                status="needs_input",
                output=None,
                errors=("path is required for data analysis",),
                metadata={"kind": "missing_dataset_path"},
            )

        path = Path(str(path_value)).expanduser()
        if not path.exists():
            return AgentResult(
                task_id=task.task_id,
                status="blocked",
                output=None,
                errors=(f"dataset not found: {path}",),
                metadata={"kind": "missing_dataset_file"},
            )

        mode = str(task.inputs.get("mode") or task.inputs.get("operation") or "profile").strip().lower()
        if mode in {"analyze", "analysis", "question", "query", "answer"}:
            question = str(task.inputs.get("question") or task.objective).strip()
            if not question:
                return AgentResult(
                    task_id=task.task_id,
                    status="needs_input",
                    output=None,
                    errors=("question is required for analysis mode",),
                    metadata={"kind": "missing_analysis_question"},
                )
            try:
                result = answer_question(path, question)
            except Exception as exc:  # pragma: no cover - defensive fail-closed path
                return AgentResult(
                    task_id=task.task_id,
                    status="failed",
                    output=None,
                    errors=(f"{type(exc).__name__}: {exc}",),
                    metadata={"kind": "analysis_failure"},
                )
            return AgentResult(
                task_id=task.task_id,
                status="success",
                output=result,
                evidence=(f"dataset:{path}", "tool:analyze_dataset"),
                metadata={"kind": "dataset_analysis", "mode": "analyze", "path": str(path)},
            )

        try:
            profile = profile_dataset(path)
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            return AgentResult(
                task_id=task.task_id,
                status="failed",
                output=None,
                errors=(f"{type(exc).__name__}: {exc}",),
                metadata={"kind": "profile_failure"},
            )

        payload = {
            "source": profile.source,
            "fingerprint": profile.fingerprint,
            "rows": profile.rows,
            "columns": profile.columns,
            "duplicate_rows": profile.duplicate_rows,
            "quality_score": profile.quality_score,
            "warnings": list(profile.warnings),
            "column_profiles": [
                {
                    "name": c.name,
                    "inferred_type": c.inferred_type,
                    "count": c.count,
                    "missing": c.missing,
                    "missing_rate": c.missing_rate,
                    "unique": c.unique,
                    "constant": c.constant,
                    "min": c.min,
                    "max": c.max,
                    "mean": c.mean,
                    "median": c.median,
                    "stddev": c.stddev,
                    "q1": c.q1,
                    "q3": c.q3,
                    "outliers": c.outliers,
                    "outlier_rate": c.outlier_rate,
                    "top_values": list(c.top_values) if c.top_values is not None else [],
                }
                for c in profile.column_profiles
            ],
            "correlations": list(profile.correlations),
        }
        return AgentResult(
            task_id=task.task_id,
            status="success",
            output=payload,
            evidence=(f"dataset:{path}", "tool:profile_dataset"),
            metadata={"kind": "dataset_profile", "mode": "profile", "path": str(path)},
        )

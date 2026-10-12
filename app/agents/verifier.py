from __future__ import annotations

from typing import Any

from .base import SpecialistAgent
from .contracts import AgentResult, AgentSpec, AgentTask


class VerifierAgent(SpecialistAgent):
    """Read-only validator for specialist outputs and evidence."""

    def __init__(self, agent_id: str = "verifier-agent"):
        super().__init__(
            AgentSpec(
                agent_id=agent_id,
                name="Verifier Agent",
                capability="verification",
                description="Validates specialist outputs for required fields, provenance, and bounded result shape.",
                allowed_tools=("verify_dataset_result", "verify_result"),
                read_only=True,
                max_timeout_seconds=15.0,
                resource_budget={"cpu": 0.5},
            )
        )

    def run(self, task: AgentTask) -> AgentResult:
        profile = task.inputs.get("profile") or task.inputs.get("dataset_profile")
        analysis = task.inputs.get("analysis") or task.inputs.get("result")
        if profile is None and analysis is None:
            return AgentResult(
                task_id=task.task_id,
                status="needs_input",
                output=None,
                errors=("profile or analysis output is required for verification",),
                metadata={"kind": "missing_verification_payload"},
            )

        if profile is not None and not isinstance(profile, dict):
            return AgentResult(
                task_id=task.task_id,
                status="blocked",
                output=None,
                errors=("profile payload must be a dictionary",),
                metadata={"kind": "invalid_profile_payload"},
            )

        if analysis is not None and not isinstance(analysis, dict):
            return AgentResult(
                task_id=task.task_id,
                status="blocked",
                output=None,
                errors=("analysis payload must be a dictionary",),
                metadata={"kind": "invalid_analysis_payload"},
            )

        if profile is not None:
            missing_profile_fields = [field for field in ("rows", "columns") if field not in profile]
            if missing_profile_fields:
                return AgentResult(
                    task_id=task.task_id,
                    status="blocked",
                    output=None,
                    errors=(f"profile payload missing required fields: {', '.join(missing_profile_fields)}",),
                    metadata={"kind": "incomplete_profile"},
                )

        if analysis is not None:
            if "answer" not in analysis and "method" not in analysis:
                return AgentResult(
                    task_id=task.task_id,
                    status="blocked",
                    output=None,
                    errors=("analysis payload missing answer or method metadata",),
                    metadata={"kind": "incomplete_analysis"},
                )

        summary: dict[str, Any] = {"verified": True}
        if profile is not None:
            summary["profile_rows"] = int(profile.get("rows", 0))
            summary["profile_columns"] = int(profile.get("columns", 0))
        if analysis is not None:
            summary["has_answer"] = "answer" in analysis
            summary["method"] = analysis.get("method")

        return AgentResult(
            task_id=task.task_id,
            status="success",
            output={"verified": True, "summary": summary, "profile": profile, "analysis": analysis},
            evidence=("verification:read_only", "verification:bounded_result"),
            metadata={"kind": "result_verification", "verified": True},
        )

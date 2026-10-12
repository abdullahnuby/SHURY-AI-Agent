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
            try:
                rows = int(profile.get("rows", 0))
                columns = int(profile.get("columns", 0))
            except (TypeError, ValueError):
                return AgentResult(
                    task_id=task.task_id,
                    status="blocked",
                    output=None,
                    errors=("profile rows and columns must be integers",),
                    metadata={"kind": "invalid_profile_dimensions"},
                )
            if rows < 0 or columns < 0:
                return AgentResult(
                    task_id=task.task_id,
                    status="blocked",
                    output=None,
                    errors=("profile rows and columns cannot be negative",),
                    metadata={"kind": "invalid_profile_dimensions"},
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
            if "method" in analysis and (not isinstance(analysis.get("method"), str) or not str(analysis.get("method")).strip()):
                return AgentResult(
                    task_id=task.task_id,
                    status="blocked",
                    output=None,
                    errors=("analysis method must be a non-empty string",),
                    metadata={"kind": "invalid_analysis_method"},
                )
            if "answer" in analysis:
                answer = analysis.get("answer")
                if answer is None or answer == {}:
                    return AgentResult(
                        task_id=task.task_id,
                        status="blocked",
                        output=None,
                        errors=("analysis answer cannot be null or empty",),
                        metadata={"kind": "empty_analysis_answer"},
                    )
            if profile is not None:
                profile_fingerprint = profile.get("fingerprint")
                analysis_fingerprint = analysis.get("fingerprint") or analysis.get("source_fingerprint") or analysis.get("source")
                if profile_fingerprint and analysis_fingerprint and str(profile_fingerprint) != str(analysis_fingerprint):
                    return AgentResult(
                        task_id=task.task_id,
                        status="blocked",
                        output=None,
                        errors=("analysis fingerprint does not match the dataset profile",),
                        metadata={"kind": "fingerprint_mismatch"},
                    )

        summary: dict[str, Any] = {"verified": True}
        if profile is not None:
            summary["profile_rows"] = int(profile.get("rows", 0))
            summary["profile_columns"] = int(profile.get("columns", 0))
        if analysis is not None:
            summary["has_answer"] = "answer" in analysis and analysis.get("answer") is not None
            summary["method"] = analysis.get("method")

        return AgentResult(
            task_id=task.task_id,
            status="success",
            output={"verified": True, "summary": summary, "profile": profile, "analysis": analysis},
            evidence=("verification:read_only", "verification:bounded_result", "verification:content_check"),
            metadata={"kind": "result_verification", "verified": True},
        )

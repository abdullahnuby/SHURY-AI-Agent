from __future__ import annotations

from app.integrations.devops import git_status, inspect_project

from .base import SpecialistAgent
from .contracts import AgentResult, AgentSpec, AgentTask


class DevelopmentAgent(SpecialistAgent):
    """Read-only specialist for project inspection and repository status."""

    def __init__(self, agent_id: str = "development-agent"):
        super().__init__(
            AgentSpec(
                agent_id=agent_id,
                name="Development Agent",
                capability="development",
                description="Inspects the project and git state without modifying the workspace or running arbitrary build commands.",
                allowed_tools=("inspect_project", "git_status"),
                read_only=True,
                max_timeout_seconds=20.0,
                resource_budget={"cpu": 0.5, "disk_io": 0.5},
            )
        )

    def run(self, task: AgentTask) -> AgentResult:
        path = task.inputs.get("path") or task.inputs.get("project") or "."
        if not path or str(path).strip() == "":
            return AgentResult(
                task_id=task.task_id,
                status="needs_input",
                output=None,
                errors=("path is required for development inspection",),
                metadata={"kind": "missing_project_path"},
            )

        try:
            project = inspect_project(str(path))
            git = git_status(str(path))
        except ValueError as exc:
            return AgentResult(
                task_id=task.task_id,
                status="blocked",
                output=None,
                errors=(f"{type(exc).__name__}: {exc}",),
                metadata={"kind": "unsafe_project_path"},
            )
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            return AgentResult(
                task_id=task.task_id,
                status="failed",
                output=None,
                errors=(f"{type(exc).__name__}: {exc}",),
                metadata={"kind": "development_inspection_failure"},
            )

        payload = {
            "path": project.get("path") or str(path),
            "stack": project.get("stack", []),
            "commands": project.get("commands", []),
            "metadata": project.get("metadata", {}),
            "git": git,
        }
        return AgentResult(
            task_id=task.task_id,
            status="success",
            output=payload,
            evidence=("development:inspect_project", "development:git_status"),
            metadata={"kind": "development_summary", "path": payload["path"]},
        )

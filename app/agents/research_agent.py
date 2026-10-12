from __future__ import annotations

from typing import Any

from app.services.research_service import research_sources, research_status

from .base import SpecialistAgent
from .contracts import AgentResult, AgentSpec, AgentTask


class ResearchAgent(SpecialistAgent):
    """Read-only specialist for bounded research and evidence retrieval."""

    def __init__(self, agent_id: str = "research-agent"):
        super().__init__(
            AgentSpec(
                agent_id=agent_id,
                name="Research Agent",
                capability="research",
                description="Searches bounded research memory for prior evidence and source context without changing system state.",
                allowed_tools=("research_memory_search", "research_source_learning", "research_status"),
                read_only=True,
                max_timeout_seconds=20.0,
                resource_budget={"cpu": 0.5, "memory": 0.5},
            )
        )

    def run(self, task: AgentTask) -> AgentResult:
        query = str(task.inputs.get("query") or task.inputs.get("question") or task.objective or "").strip()
        if not query:
            return AgentResult(
                task_id=task.task_id,
                status="needs_input",
                output=None,
                errors=("query is required for research tasks",),
                metadata={"kind": "missing_research_query"},
            )

        try:
            evidence = research_sources(query, limit=int(task.inputs.get("limit") or 10))
            status = research_status()
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            return AgentResult(
                task_id=task.task_id,
                status="failed",
                output=None,
                errors=(f"{type(exc).__name__}: {exc}",),
                metadata={"kind": "research_failure"},
            )

        items = evidence if isinstance(evidence, list) else []
        source_count = len(items)
        payload = {
            "query": query,
            "evidence": items,
            "source_count": source_count,
            "memory_status": status,
        }
        return AgentResult(
            task_id=task.task_id,
            status="success",
            output=payload,
            evidence=("research:read_only", "research:memory"),
            metadata={"kind": "research_summary", "query": query, "source_count": source_count},
        )

from __future__ import annotations

from .contracts import AgentResult, AgentTask
from .registry import AgentRegistry


class AgentDispatcher:
    """Thin coordinator that keeps policy enforcement inside the registry boundary."""

    def __init__(self, registry: AgentRegistry | None = None):
        self.registry = registry or AgentRegistry()

    def dispatch(self, task: AgentTask) -> AgentResult:
        return self.registry.dispatch(task)


__all__ = ["AgentDispatcher"]

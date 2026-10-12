from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

from .base import SpecialistAgent
from .contracts import AgentResult, AgentSpec, AgentTask


class InertAgent(SpecialistAgent):
    """Default no-op specialist used to establish the registry contract without side effects."""

    def __init__(self, agent_id: str = "inert-agent", capability: str = "noop"):
        super().__init__(
            AgentSpec(
                agent_id=agent_id,
                name="Inert Agent",
                capability=capability,
                description="No-operation specialist used for contract-level validation.",
                read_only=True,
                max_timeout_seconds=5.0,
            )
        )

    def run(self, task: AgentTask) -> AgentResult:
        if not task.validate():
            return AgentResult(
                task_id=task.task_id,
                status="success",
                output={"status": "noop", "objective": task.objective},
                evidence=("registry:no-op",),
            )
        return AgentResult(
            task_id=task.task_id,
            status="blocked",
            output=None,
            errors=("task validation failed",),
        )


class AgentRegistry:
    def __init__(self, agents: list[SpecialistAgent] | None = None):
        self._agents: dict[str, SpecialistAgent] = {}
        self._by_capability: dict[str, SpecialistAgent] = {}
        for agent in agents or ():
            self.register(agent)

    def register(self, agent: SpecialistAgent) -> SpecialistAgent:
        if not isinstance(agent, SpecialistAgent):
            raise TypeError("agent must inherit from SpecialistAgent")
        if agent.agent_id in self._agents:
            raise ValueError(f"Duplicate agent id: {agent.agent_id}")
        if agent.spec.capability in self._by_capability:
            raise ValueError(f"Duplicate capability: {agent.spec.capability}")
        self._agents[agent.agent_id] = agent
        self._by_capability[agent.spec.capability] = agent
        return agent

    def get(self, agent_id: str) -> SpecialistAgent | None:
        return self._agents.get(agent_id)

    def resolve(self, capability: str) -> SpecialistAgent | None:
        return self._by_capability.get(capability)

    def validate_task(self, task: AgentTask) -> list[str]:
        errors = task.validate()
        if not errors and not task.capability:
            errors.append("capability is required")
        return errors

    def dispatch(self, task: AgentTask) -> AgentResult:
        errors = self.validate_task(task)
        if errors:
            return AgentResult(
                task_id=task.task_id,
                status="blocked",
                errors=tuple(errors),
                metadata={"kind": "task_validation"},
            )
        agent = self.resolve(task.capability)
        if agent is None:
            return AgentResult(
                task_id=task.task_id,
                status="blocked",
                errors=(f"unknown capability: {task.capability}",),
                metadata={"kind": "capability_resolution"},
            )
        timeout_limit = float(task.timeout_seconds)
        max_timeout = float(agent.spec.max_timeout_seconds)
        if timeout_limit <= 0 or max_timeout <= 0:
            return AgentResult(
                task_id=task.task_id,
                status="blocked",
                errors=("timeout must be positive for specialist execution",),
                metadata={"kind": "invalid_timeout"},
            )
        timeout_limit = min(timeout_limit, max_timeout)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(agent.run, task)
                result = future.result(timeout=timeout_limit)
        except FutureTimeoutError:
            return AgentResult(
                task_id=task.task_id,
                status="timeout",
                errors=(f"agent timed out after {timeout_limit:.3f}s",),
                metadata={"kind": "execution_timeout", "timeout_seconds": timeout_limit},
            )
        except TimeoutError:
            return AgentResult(
                task_id=task.task_id,
                status="timeout",
                errors=(f"agent timed out after {timeout_limit:.3f}s",),
                metadata={"kind": "execution_timeout", "timeout_seconds": timeout_limit},
            )
        except Exception as exc:  # pragma: no cover - default fail-closed path
            return AgentResult(
                task_id=task.task_id,
                status="failed",
                errors=(f"{type(exc).__name__}: {exc}",),
                metadata={"kind": "execution_exception"},
            )

        if not isinstance(result, AgentResult):
            return AgentResult(
                task_id=task.task_id,
                status="blocked",
                errors=("agent returned a non-AgentResult payload",),
                metadata={"kind": "result_type_validation"},
            )

        if result.task_id != task.task_id:
            return AgentResult(
                task_id=task.task_id,
                status="blocked",
                errors=(f"task_id mismatch: expected {task.task_id}, got {result.task_id}",),
                metadata={"kind": "result_task_id_mismatch", "expected_task_id": task.task_id, "actual_task_id": result.task_id},
            )

        validation_errors = agent.validate_result(result)
        if validation_errors:
            return AgentResult(
                task_id=task.task_id,
                status="blocked",
                errors=tuple(validation_errors),
                metadata={"kind": "result_validation"},
            )
        return result


def register_agent(agent: SpecialistAgent, registry: AgentRegistry | None = None) -> SpecialistAgent:
    reg = registry or AgentRegistry()
    reg.register(agent)
    return agent


def resolve_agent(capability: str, registry: AgentRegistry | None = None) -> SpecialistAgent | None:
    reg = registry or AgentRegistry()
    return reg.resolve(capability)


__all__ = ["AgentRegistry", "InertAgent", "SpecialistAgent", "register_agent", "resolve_agent"]

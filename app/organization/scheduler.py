from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import CompanyTask, ExecutionWave


@dataclass(frozen=True)
class ScheduleBatch:
    wave: int
    task_ids: tuple[str, ...]
    mode: str  # parallel | serial
    estimated_duration: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "wave": self.wave,
            "task_ids": list(self.task_ids),
            "mode": self.mode,
            "estimated_duration": self.estimated_duration,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CompanySchedule:
    batches: tuple[ScheduleBatch, ...]
    serial_duration: float
    scheduled_duration: float
    max_parallelism: int
    errors: tuple[str, ...] = ()

    @property
    def parallel_batches(self) -> int:
        return sum(1 for batch in self.batches if batch.mode == "parallel" and len(batch.task_ids) > 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batches": [b.to_dict() for b in self.batches],
            "serial_duration": self.serial_duration,
            "scheduled_duration": self.scheduled_duration,
            "max_parallelism": self.max_parallelism,
            "parallel_batches": self.parallel_batches,
            "errors": list(self.errors),
        }


class CompanyScheduler:
    """Deterministic scheduler for Company DAG execution.

    The DAG/dependencies remain authoritative. Scheduling only decides which already-ready
    tasks may share an execution batch. A task opts into concurrency through the existing
    Tool.parallel_safe contract; approval-gated or resource-conflicting actions remain serial.
    """

    def __init__(self, *, default_max_parallelism: int = 4):
        self.default_max_parallelism = max(1, int(default_max_parallelism))

    @staticmethod
    def _tool_duration(tool: Any) -> float:
        try:
            return max(0.0, float(getattr(tool, "duration", 0.0) or 0.0))
        except Exception:
            return 0.0

    @staticmethod
    def _parallel_eligible(task: CompanyTask, tool: Any) -> tuple[bool, str]:
        if tool is None:
            return False, "unknown_tool"
        if not bool(getattr(tool, "parallel_safe", False)):
            return False, "tool_not_parallel_safe"
        if bool(getattr(tool, "requires_approval", False)):
            return False, "approval_gated"
        if tuple(getattr(tool, "exclusive_resources", ()) or ()):
            return False, "exclusive_resource"
        if getattr(task, "authority", "autonomous") != "autonomous":
            return False, "non_autonomous_authority"
        return True, "parallel_safe"

    @staticmethod
    def _resource_overlap(tasks: Iterable[CompanyTask], registry: dict[str, Any]) -> bool:
        seen: set[str] = set()
        for task in tasks:
            tool = registry.get(task.tool)
            for resource in tuple(getattr(tool, "exclusive_resources", ()) or ()):
                if resource in seen:
                    return True
                seen.add(resource)
        return False

    def schedule(self, tasks: Iterable[CompanyTask], waves: Iterable[ExecutionWave] = (),
                 registry: dict[str, Any] | None = None, *, max_parallelism: int | None = None) -> CompanySchedule:
        registry = registry or {}
        limit = max(1, int(max_parallelism or self.default_max_parallelism))
        ordered_tasks = tuple(tasks or ())
        by_id = {task.task_id: task for task in ordered_tasks}
        logical_waves = tuple(waves or ())
        errors: list[str] = []
        if not logical_waves and ordered_tasks:
            # Defensive fallback: one deterministic wave. Dependencies are still checked by the
            # decomposer; this path only serves callers that provide tasks directly.
            logical_waves = (ExecutionWave(1, tuple(task.task_id for task in ordered_tasks)),)

        batches: list[ScheduleBatch] = []
        serial_duration = 0.0
        scheduled_duration = 0.0

        for wave in logical_waves:
            ids = [task_id for task_id in wave.task_ids if task_id in by_id]
            ready = [by_id[task_id] for task_id in ids]
            parallel_pool: list[CompanyTask] = []
            serial_tasks: list[CompanyTask] = []
            for task in ready:
                tool = registry.get(task.tool)
                eligible, reason = self._parallel_eligible(task, tool)
                if eligible:
                    parallel_pool.append(task)
                else:
                    serial_tasks.append(task)
                    serial_duration += self._tool_duration(tool)
                    scheduled_duration += self._tool_duration(tool)
                    batches.append(ScheduleBatch(
                        wave=wave.wave,
                        task_ids=(task.task_id,),
                        mode="serial",
                        estimated_duration=self._tool_duration(tool),
                        reason=reason,
                    ))
                    if reason == "unknown_tool":
                        errors.append(f"unknown_tool:{task.task_id}:{task.tool}")

            # Stable resource-aware chunking even if future tools begin declaring exclusives.
            for start in range(0, len(parallel_pool), limit):
                chunk = parallel_pool[start:start + limit]
                if len(chunk) == 1:
                    task = chunk[0]
                    duration = self._tool_duration(registry.get(task.tool))
                    serial_duration += duration
                    scheduled_duration += duration
                    batches.append(ScheduleBatch(wave.wave, (task.task_id,), "serial", duration, "single_ready_task"))
                    continue
                if self._resource_overlap(chunk, registry):
                    # Split deterministically rather than racing two writers.
                    for task in chunk:
                        duration = self._tool_duration(registry.get(task.tool))
                        serial_duration += duration
                        scheduled_duration += duration
                        batches.append(ScheduleBatch(wave.wave, (task.task_id,), "serial", duration, "resource_conflict"))
                    continue
                ids_chunk = tuple(task.task_id for task in chunk)
                duration = max((self._tool_duration(registry.get(task.tool)) for task in chunk), default=0.0)
                serial_duration += sum(self._tool_duration(registry.get(task.tool)) for task in chunk)
                scheduled_duration += duration
                batches.append(ScheduleBatch(wave.wave, ids_chunk, "parallel", duration, "independent_parallel_safe_tasks"))

        return CompanySchedule(tuple(batches), round(serial_duration, 6), round(scheduled_duration, 6), limit, tuple(dict.fromkeys(errors)))

    def ready_batch(self, actions: Iterable[Any], outputs: dict[str, Any], registry: dict[str, Any], *, limit: int | None = None) -> tuple[Any, ...]:
        """Return the largest currently-ready safe batch, deterministically ordered."""
        max_size = max(1, int(limit or self.default_max_parallelism))
        ready = [action for action in tuple(actions or ()) if all(dep in outputs for dep in tuple(action.depends_on or ()))]
        if len(ready) < 2:
            return tuple(ready[:1])
        safe: list[Any] = []
        for action in ready:
            tool = registry.get(action.tool)
            if tool is None or not bool(getattr(tool, "parallel_safe", False)):
                continue
            if bool(getattr(tool, "requires_approval", False)):
                continue
            if tuple(getattr(tool, "exclusive_resources", ()) or ()):
                continue
            if getattr(action, "exploration_mode", ""):
                continue
            safe.append(action)
        if len(safe) < 2:
            return tuple(ready[:1])
        batch = tuple(safe[:max_size])
        # Never co-run a pair with overlapping exclusive resources, even if a future tool's
        # metadata incorrectly marks it parallel-safe.
        resource_seen: set[str] = set()
        filtered: list[Any] = []
        for action in batch:
            tool = registry.get(action.tool)
            resources = set(getattr(tool, "exclusive_resources", ()) or ())
            if resource_seen.intersection(resources):
                break
            resource_seen.update(resources)
            filtered.append(action)
        return tuple(filtered) if len(filtered) >= 2 else tuple(ready[:1])

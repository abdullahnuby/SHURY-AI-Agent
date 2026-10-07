from __future__ import annotations

"""Multi-horizon company state built on SHURY's existing LearningStore/Memory.

This module deliberately does not create a second memory backend. Portfolio/project state is
persisted in the canonical LearningStore, while durable organizational knowledge remains in
CompanyMemory. Specialist identities are stable role identifiers plus persisted execution evidence.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import math
from typing import Any, Iterable

from app.learning.store import LearningStore
from app.organization.company_memory import CompanyMemory


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


@dataclass(frozen=True)
class CompanyProject:
    project_id: str
    name: str
    objective: str
    priority: float = 0.5
    horizon: str = "medium"
    status: str = "active"
    criticality: float = 0.5
    metadata: dict[str, Any] | None = None
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = dict(self.metadata or {})
        return data


@dataclass(frozen=True)
class CompanyProjectTask:
    project_id: str
    task_id: str
    objective: str
    department: str = ""
    specialist: str = ""
    priority: float = 0.5
    horizon: str = "medium"
    status: str = "pending"
    depends_on: tuple[str, ...] = ()
    estimated_duration: float = 0.0
    exclusive_resources: tuple[str, ...] = ()
    ready: bool = True
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["depends_on"] = list(self.depends_on)
        data["exclusive_resources"] = list(self.exclusive_resources)
        return data


@dataclass(frozen=True)
class SpecialistIdentity:
    identity_key: str
    role_key: str
    department: str
    name: str
    remit: str
    skills: tuple[str, ...]
    capabilities: tuple[str, ...]
    total_attempts: int = 0
    verified_successes: int = 0
    verified_failures: int = 0
    success_rate: float = 0.0
    active_tasks: int = 0
    workload_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["skills"] = list(self.skills)
        data["capabilities"] = list(self.capabilities)
        data["success_rate"] = round(self.success_rate, 4)
        data["workload_score"] = round(self.workload_score, 4)
        return data


class CompanyPortfolioError(ValueError):
    pass


class CompanyPortfolioManager:
    """Persist and coordinate multiple active projects without leaking task state between them."""

    def __init__(self, *, learning_store: LearningStore | None = None,
                 company_memory: CompanyMemory | None = None, company_id: str = "shury-company"):
        self.learning = learning_store or LearningStore()
        self.company_memory = company_memory or CompanyMemory(company_id=company_id)
        self.company_id = company_id

    def create_project(self, project_id: str, name: str, objective: str, *, priority: float = 0.5,
                       horizon: str = "medium", criticality: float = 0.5, metadata: dict[str, Any] | None = None) -> CompanyProject:
        project_id = str(project_id or "").strip()
        if not project_id:
            raise CompanyPortfolioError("project_id is required")
        if self.get_project(project_id) is not None:
            raise CompanyPortfolioError(f"project already exists: {project_id}")
        now = _now()
        project = CompanyProject(project_id, str(name or project_id).strip(), str(objective or "").strip(),
                                 max(0.0, min(1.0, float(priority))), str(horizon or "medium").strip().casefold(),
                                 "active", max(0.0, min(1.0, float(criticality))), dict(metadata or {}), 1, now, now)
        self.learning.create_company_project(project.to_dict())
        return project

    def get_project(self, project_id: str) -> CompanyProject | None:
        row = self.learning.get_company_project(str(project_id or ""))
        return self._project(row) if row else None

    @staticmethod
    def _project(row: dict[str, Any]) -> CompanyProject:
        return CompanyProject(
            project_id=str(row["project_id"]), name=str(row["name"]), objective=str(row["objective"]),
            priority=float(row.get("priority") or 0.5), horizon=str(row.get("horizon") or "medium"),
            status=str(row.get("status") or "active"), criticality=float(row.get("criticality") or 0.5),
            metadata=dict(row.get("metadata") or {}), version=int(row.get("version") or 1),
            created_at=str(row.get("created_at") or ""), updated_at=str(row.get("updated_at") or ""),
        )

    def list_projects(self, *, active_only: bool = False) -> tuple[CompanyProject, ...]:
        rows = self.learning.list_company_projects(active_only=active_only)
        return tuple(self._project(row) for row in rows)

    def update_project(self, project_id: str, **changes: Any) -> CompanyProject:
        current = self.get_project(project_id)
        if current is None:
            raise CompanyPortfolioError(f"unknown project: {project_id}")
        allowed = {"name", "objective", "priority", "horizon", "status", "criticality", "metadata"}
        payload = {k: v for k, v in changes.items() if k in allowed}
        if "priority" in payload:
            payload["priority"] = max(0.0, min(1.0, float(payload["priority"])))
        if "criticality" in payload:
            payload["criticality"] = max(0.0, min(1.0, float(payload["criticality"])))
        if "horizon" in payload:
            payload["horizon"] = str(payload["horizon"]).casefold()
        self.learning.update_company_project(project_id, payload)
        return self.get_project(project_id)  # type: ignore[return-value]

    def upsert_task(self, task: CompanyProjectTask) -> CompanyProjectTask:
        if self.get_project(task.project_id) is None:
            raise CompanyPortfolioError(f"unknown project: {task.project_id}")
        clean_deps = tuple(dict.fromkeys(str(x) for x in task.depends_on if str(x)))
        if task.task_id in clean_deps:
            raise CompanyPortfolioError("project task cannot depend on itself")
        normalized = CompanyProjectTask(
            project_id=str(task.project_id), task_id=str(task.task_id), objective=str(task.objective),
            department=str(task.department), specialist=str(task.specialist),
            priority=max(0.0, min(1.0, float(task.priority))), horizon=str(task.horizon or "medium").casefold(),
            status=str(task.status or "pending"), depends_on=clean_deps,
            estimated_duration=max(0.0, float(task.estimated_duration or 0.0)),
            exclusive_resources=tuple(dict.fromkeys(str(x) for x in task.exclusive_resources if str(x))),
            ready=bool(task.ready), created_at=task.created_at or _now(), updated_at=_now(),
        )
        self.learning.upsert_company_project_task(normalized.to_dict())
        return normalized

    def list_tasks(self, project_id: str, *, active_only: bool = False) -> tuple[CompanyProjectTask, ...]:
        return tuple(self._task(row) for row in self.learning.list_company_project_tasks(project_id, active_only=active_only))

    @staticmethod
    def _task(row: dict[str, Any]) -> CompanyProjectTask:
        return CompanyProjectTask(
            project_id=str(row["project_id"]), task_id=str(row["task_id"]), objective=str(row.get("objective") or ""),
            department=str(row.get("department") or ""), specialist=str(row.get("specialist") or ""),
            priority=float(row.get("priority") or 0.5), horizon=str(row.get("horizon") or "medium"),
            status=str(row.get("status") or "pending"),
            depends_on=tuple(row.get("depends_on") or ()), estimated_duration=float(row.get("estimated_duration") or 0.0),
            exclusive_resources=tuple(row.get("exclusive_resources") or ()), ready=bool(row.get("ready", True)),
            created_at=str(row.get("created_at") or ""), updated_at=str(row.get("updated_at") or ""),
        )

    def reprioritize(self, *, active_only: bool = True) -> tuple[dict[str, Any], ...]:
        """Return deterministic cross-project order; does not mutate ownership or task state."""
        projects = self.list_projects(active_only=active_only)
        rows = []
        for project in projects:
            tasks = self.list_tasks(project.project_id, active_only=True)
            dependency_wait = sum(1 for task in tasks if task.depends_on and not task.ready)
            load = len(tasks)
            horizon_weight = {"immediate": 1.0, "short": 0.85, "medium": 0.65, "long": 0.45}.get(project.horizon, 0.6)
            aging = 0.0
            if project.updated_at:
                try:
                    age_days = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(project.updated_at)).total_seconds() / 86400.0)
                    aging = min(1.0, age_days / 30.0)
                except Exception:
                    aging = 0.0
            score = (0.45 * project.priority + 0.25 * project.criticality + 0.20 * horizon_weight + 0.10 * aging)
            score -= 0.03 * min(load, 10)
            score -= 0.02 * min(dependency_wait, 10)
            rows.append({"project_id": project.project_id, "priority_score": round(max(0.0, score), 6),
                         "priority": project.priority, "criticality": project.criticality,
                         "horizon": project.horizon, "active_task_count": load, "waiting_dependencies": dependency_wait})
        return tuple(sorted(rows, key=lambda r: (-r["priority_score"], r["project_id"])))

    def sync_coordination(self, project_id: str, coordination: dict[str, Any]) -> tuple[CompanyProjectTask, ...]:
        if not str(project_id or '').strip():
            return ()
        project = self.get_project(project_id)
        if project is None:
            raise CompanyPortfolioError(f"unknown project: {project_id}")
        synced: list[CompanyProjectTask] = []
        for row in coordination.get("tasks") or ():
            if not isinstance(row, dict):
                continue
            task = CompanyProjectTask(
                project_id=str(project_id), task_id=str(row.get("step_id") or row.get("task_id") or ""),
                objective=str(row.get("objective") or project.objective),
                department=str(row.get("department") or ''), specialist=str(row.get("specialist") or ''),
                priority=float(row.get("priority", project.priority)), horizon=str(row.get("horizon") or project.horizon),
                status=str(row.get("status") or "pending"),
                depends_on=tuple(str(x) for x in (row.get("depends_on") or ())),
                estimated_duration=float(row.get("estimated_duration") or 0.0),
                exclusive_resources=tuple(str(x) for x in (row.get("exclusive_resources") or ())),
                ready=True,
            )
            if not task.task_id:
                continue
            synced.append(self.upsert_task(task))
        return tuple(synced)

    def mark_task_status(self, project_id: str, task_id: str, status: str) -> CompanyProjectTask | None:
        tasks = self.list_tasks(project_id)
        current = next((task for task in tasks if task.task_id == str(task_id)), None)
        if current is None:
            return None
        updated = CompanyProjectTask(
            project_id=current.project_id, task_id=current.task_id, objective=current.objective,
            department=current.department, specialist=current.specialist, priority=current.priority, horizon=current.horizon,
            status=str(status), depends_on=current.depends_on, estimated_duration=current.estimated_duration,
            exclusive_resources=current.exclusive_resources, ready=current.ready,
            created_at=current.created_at, updated_at=_now(),
        )
        self.learning.upsert_company_project_task(updated.to_dict())
        return updated

    def ready_tasks(self, project_id: str) -> tuple[CompanyProjectTask, ...]:
        tasks = self.list_tasks(project_id, active_only=True)
        done = {t.task_id for t in tasks if t.status in {"completed", "verified"}}
        return tuple(t for t in tasks if t.status in {"pending", "ready"} and t.ready and all(dep in done for dep in t.depends_on))

    def specialist_identity(self, role_key: str, organization) -> SpecialistIdentity:
        role = organization.role(role_key)
        evidence = self.learning.company_delegation_evidence(limit=500)
        own = [row for row in evidence if str(row.get("specialist")) == role_key]
        attempts = sum(int(row.get("attempts") or 0) for row in own)
        successes = sum(int(row.get("verified_successes") or 0) for row in own)
        failures = sum(int(row.get("verified_failures") or 0) for row in own)
        active = sum(1 for project in self.list_projects(active_only=True) for task in self.list_tasks(project.project_id, active_only=True) if task.specialist == role_key)
        success_rate = successes / max(1, attempts)
        workload = min(1.0, active / 5.0)
        return SpecialistIdentity(
            identity_key=f"specialist:{role_key}", role_key=role_key, department=role.department, name=role.name,
            remit=role.remit, skills=role.skills, capabilities=role.capabilities,
            total_attempts=attempts, verified_successes=successes, verified_failures=failures,
            success_rate=success_rate, active_tasks=active, workload_score=workload,
        )

    def all_specialist_identities(self, organization) -> tuple[SpecialistIdentity, ...]:
        keys = [role.key for role in organization.roles if role.agent_class == "builder"]
        return tuple(self.specialist_identity(key, organization) for key in sorted(keys))

    def recall_project_memory(self, objective: str, *, project_id: str, top_k: int = 6):
        return self.company_memory.recall_for_goal(objective, top_k=top_k, project_id=project_id)

    def snapshot(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "active_projects": [p.to_dict() for p in self.list_projects(active_only=True)],
            "project_order": list(self.reprioritize(active_only=True)),
            "specialist_identities": [x.to_dict() for x in self.all_specialist_identities(self._organization())],
        }

    def _organization(self):
        from .company import DEFAULT_COMPANY
        return DEFAULT_COMPANY.registry

"""Explicit world state with typed facts, resources, time and deterministic transitions."""
from dataclasses import dataclass, field
from typing import Any
import hashlib
import json


@dataclass(frozen=True)
class StateDelta:
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()
    variables: dict[str, Any] = field(default_factory=dict)
    resource_delta: tuple[tuple[str, float], ...] = ()


@dataclass
class WorldState:
    facts: dict[str, str] = field(default_factory=dict)
    variables: dict[str, object] = field(default_factory=dict)
    capabilities: set[str] = field(default_factory=set)
    resources: dict[str, float] = field(default_factory=dict)
    elapsed: float = 0.0
    last_goal: str = ""
    last_outputs: dict[str, object] = field(default_factory=dict)
    completed_goals: list[str] = field(default_factory=list)
    failed_goals: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    entities: dict[str, dict] = field(default_factory=dict)
    relations: dict[str, dict] = field(default_factory=dict)
    observations: list[dict] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    environment_conditions: dict[str, Any] = field(default_factory=dict)
    temporal_context: list[str] = field(default_factory=list)
    learned_features: dict[str, Any] = field(default_factory=dict)
    version: int = 0

    def snapshot(self) -> dict:
        return {
            "facts": dict(self.facts),
            "variables": dict(self.variables),
            "capabilities": sorted(self.capabilities),
            "resources": dict(self.resources),
            "elapsed": self.elapsed,
            "last_goal": self.last_goal,
            "last_outputs": dict(self.last_outputs),
            "completed_goals": list(self.completed_goals),
            "failed_goals": list(self.failed_goals),
            "history": list(self.history[-50:]),
            "entities": dict(self.entities),
            "relations": dict(self.relations),
            "observations": list(self.observations[-50:]),
            "uncertainties": list(self.uncertainties[-50:]),
            "constraints": list(self.constraints),
            "environment_conditions": dict(self.environment_conditions),
            "temporal_context": list(self.temporal_context),
            "learned_features": dict(self.learned_features),
            "version": self.version,
        }

    @classmethod
    def from_snapshot(cls, data: dict | None) -> "WorldState":
        data = data or {}
        return cls(
            facts=dict(data.get("facts", {})),
            variables=dict(data.get("variables", {})),
            capabilities=set(data.get("capabilities", [])),
            resources={k: float(v) for k, v in dict(data.get("resources", {})).items()},
            elapsed=float(data.get("elapsed", 0.0)),
            last_goal=str(data.get("last_goal", "")),
            last_outputs=dict(data.get("last_outputs", {})),
            completed_goals=list(data.get("completed_goals", [])),
            failed_goals=list(data.get("failed_goals", [])),
            history=list(data.get("history", [])),
            entities=dict(data.get("entities", {})),
            relations=dict(data.get("relations", {})),
            observations=list(data.get("observations", [])),
            uncertainties=list(data.get("uncertainties", [])),
            constraints=list(data.get("constraints", [])),
            environment_conditions=dict(data.get("environment_conditions", {})),
            temporal_context=list(data.get("temporal_context", [])),
            learned_features=dict(data.get("learned_features", {})),
            version=int(data.get("version", 0)),
        )

    def state_key(self) -> tuple:
        return (
            tuple(sorted(self.capabilities)),
            tuple(sorted((k, str(v)) for k, v in self.facts.items())),
            tuple(sorted((k, str(v)) for k, v in self.variables.items())),
            tuple(sorted((k, round(v, 6)) for k, v in self.resources.items())),
            tuple(sorted((k, str(v)) for k, v in self.entities.items())),
            tuple(sorted((k, str(v)) for k, v in self.relations.items())),
            round(self.elapsed, 3),
        )

    def fingerprint(self) -> str:
        payload = json.dumps(self.snapshot(), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def transition(self, delta: StateDelta, duration: float = 0.0, op: str = "") -> None:
        self.capabilities.update(delta.add)
        self.capabilities.difference_update(delta.remove)
        self.variables.update(delta.variables)
        for resource, change in delta.resource_delta:
            self.resources[resource] = self.resources.get(resource, 0.0) + float(change)
        self.elapsed += max(0.0, duration)
        self.version += 1
        self.history.append({
            "op": op,
            "add": list(delta.add),
            "remove": list(delta.remove),
            "resource_delta": list(delta.resource_delta),
            "elapsed": self.elapsed,
        })
        self.history = self.history[-50:]


def resolve_reference(text: str, world: WorldState) -> str:
    replacements = {
        "النتيجة": world.last_outputs.get("last_result"),
        "النتيجه": world.last_outputs.get("last_result"),
        "الناتج": world.last_outputs.get("last_result"),
        "اللي فات": world.last_goal,
        "الهدف السابق": world.last_goal,
    }
    out = text
    for token, value in replacements.items():
        if value is not None:
            out = out.replace(token, str(value))
    return out

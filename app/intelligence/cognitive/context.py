from __future__ import annotations
import json
from typing import Any
from app.intelligence.understanding import understand
from app.knowledge.seed_policy import CLASSIFICATION


def _clip(value: Any, limit: int) -> str:
    s = str(value or "")
    return s if len(s) <= limit else s[:limit] + f"...[truncated {len(s)-limit}]"

def tool_catalog(registry: dict, max_tools: int = 80) -> list[dict]:
    items = []
    for name, tool in sorted(registry.items()):
        items.append({
            "name": name,
            "description": _clip(tool.description, 360),
            "params": dict(tool.params),
            "capability": tool.capability or name,
            "risk": tool.risk,
            "requires_approval": bool(tool.requires_approval),
            "preconditions": list(tool.preconditions),
            "produces": list(tool.produces),
            "parallel_safe": bool(tool.parallel_safe),
        })
    return items[:max_tools]

def memory_context(mem, goal: str, limit: int = 6, session_id: str | None = None) -> dict:
    try:
        from app.knowledge.memory_controller import MemoryController
        bundle = MemoryController(mem).retrieve(goal, session_id=session_id, limit=limit, intent="memory_search")
        return bundle.to_dict()
    except Exception:
        return {}

def world_context(world) -> dict:
    observations = []
    for row in getattr(world, "observations", [])[-8:]:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item.pop("raw_output", None)
        item.pop("summary", None)
        observations.append(item)
    return {
        "capabilities": sorted(world.capabilities),
        "facts": dict(world.facts),
        "variables": dict(world.variables),
        "resources": dict(world.resources),
        "entities": dict(getattr(world, "entities", {})),
        "relations": dict(getattr(world, "relations", {})),
        "last_goal": world.last_goal,
        "last_outputs": dict(world.last_outputs),
        "completed_goals": list(world.completed_goals[-8:]),
        "failed_goals": list(world.failed_goals[-8:]),
        "recent_observations": observations,
        "uncertainties": list(getattr(world, "uncertainties", [])[-8:]),
        "version": int(getattr(world, "version", 0)),
    }

def build(goal: str, mem, world, registry: dict, baseline_plan=None, session_id: str | None = None, semantic=None) -> dict:
    u = understand(goal)
    ctx = {
        "goal": goal,
        "normalized_goal": u.normalized,
        "intents": [{"name": i.name, "score": i.score, "evidence": list(i.evidence)} for i in u.intents[:8]],
        "entities": u.entities,
        "ambiguous": u.ambiguous,
        "memory": memory_context(mem, goal, session_id=session_id),
        "world": world_context(world),
        "tools": tool_catalog(registry),
        "semantic": semantic.to_dict() if hasattr(semantic, "to_dict") else (semantic or {}),
    }
    try:
        from app.knowledge.seed_scenarios import SeedScenarioStore
        ctx["synthetic_seed_examples"] = SeedScenarioStore().context(goal, limit=4)
        ctx["synthetic_seed_policy"] = "read-only capability prior; never user memory, world knowledge, execution evidence, citation evidence, or promotion evidence"
        ctx["synthetic_seed_classification"] = CLASSIFICATION.to_dict()
    except Exception:
        ctx["synthetic_seed_examples"] = []
        ctx["synthetic_seed_policy"] = "read-only capability prior; unavailable in this environment"
        ctx["synthetic_seed_classification"] = CLASSIFICATION.to_dict()
    if baseline_plan is not None:
        ctx["deterministic_candidate"] = {
            "planner": baseline_plan.planner,
            "estimated_cost": baseline_plan.estimated_cost,
            "estimated_duration": baseline_plan.estimated_duration,
            "steps": [
                {"id": s.id, "tool": s.tool, "args": dict(s.args), "depends_on": list(s.depends_on),
                 "capability": s.capability, "clause": s.clause_text}
                for s in baseline_plan.steps[:16]
            ],
        }
    return ctx

def to_prompt(context: dict) -> str:
    return _clip(json.dumps(context, ensure_ascii=False, default=str, separators=(",", ":")), 20000)

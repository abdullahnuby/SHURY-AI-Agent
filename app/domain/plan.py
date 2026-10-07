"""Serializable execution plan with dependency and reference validation."""
from dataclasses import dataclass, field, asdict
import re
from typing import Any

REF = re.compile(r"\{\{(s\d+)(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[A-Za-z_][A-Za-z0-9_]*\])?\}\}")


@dataclass
class PlanStep:
    id: str
    tool: str
    args: dict
    status: str = "pending"
    resolved: dict | None = None
    output: Any = None
    error: str | None = None
    attempts: int = 0
    clause_index: int = 0
    clause_text: str = ""
    capability: str = ""
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Plan:
    steps: list[PlanStep] = field(default_factory=list)
    estimated_cost: float = 0.0
    estimated_duration: float = 0.0
    score: float = 0.0
    planner: str = "v9-hierarchical"
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"steps": [asdict(s) for s in self.steps],
                "estimated_cost": self.estimated_cost,
                "estimated_duration": self.estimated_duration,
                "score": self.score,
                "planner": self.planner,
                "diagnostics": self.diagnostics}

    @classmethod
    def from_dict(cls, payload: dict) -> "Plan":
        return cls([PlanStep(**s) for s in payload.get("steps", [])],
                   float(payload.get("estimated_cost", 0.0)),
                   float(payload.get("estimated_duration", 0.0)),
                   float(payload.get("score", 0.0)),
                   str(payload.get("planner", "v9-hierarchical")),
                   dict(payload.get("diagnostics", {})))


REF_TOKEN = re.compile(r"\{\{(s\d+)(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[([A-Za-z_][A-Za-z0-9_]*)\])?\}\}")


def refs_in(args: dict) -> set[str]:
    return {m.group(1) for v in args.values() if isinstance(v, str) for m in REF_TOKEN.finditer(v)}


def resolve(args: dict, outputs: dict) -> dict:
    def one(value):
        if not isinstance(value, str):
            return value
        whole = REF_TOKEN.fullmatch(value)
        if whole:
            step_id, field, bracket_field = whole.groups()
            result = outputs[step_id]
            key = field or bracket_field
            if key is None:
                return result
            if isinstance(result, dict) and key in result:
                return result[key]
            raise KeyError(f"reference {value} field not found")
        return REF_TOKEN.sub(lambda m: str(one(m.group(0))), value)
    return {k: one(v) for k, v in args.items()}


def validate(plan: Plan, registry: dict) -> list[str]:
    errors, seen = [], set()
    index = {s.id: i for i, s in enumerate(plan.steps)}
    for s in plan.steps:
        if s.id in seen:
            errors.append(f"{s.id}: id مكرر")
        t = registry.get(s.tool)
        if t is None:
            errors.append(f"{s.id}: أداة مش موجودة ({s.tool})")
        else:
            errors.extend(f"{s.id}: {e}" for e in t.validate_args(s.args))
        for dep in s.depends_on:
            if dep not in seen:
                errors.append(f"{s.id}: dependency {dep} ليست خطوة سابقة")
            elif index.get(dep, -1) >= index.get(s.id, 10**9):
                errors.append(f"{s.id}: dependency {dep} ليست قبل الخطوة")
        for r in refs_in(s.args):
            if r not in seen:
                errors.append(f"{s.id}: بيشير لـ{r} وهي مش خطوة سابقة")
        seen.add(s.id)
    # Explicitly reject dependency cycles even if a custom plan bypasses ordering checks.
    for s in plan.steps:
        visiting, visited = set(), set()
        def dfs(node_id: str) -> bool:
            if node_id in visiting:
                return True
            if node_id in visited:
                return False
            visiting.add(node_id)
            node = next((x for x in plan.steps if x.id == node_id), None)
            if node and any(dfs(d) for d in node.depends_on):
                return True
            visiting.remove(node_id)
            visited.add(node_id)
            return False
        if dfs(s.id):
            errors.append(f"{s.id}: dependency cycle")
            break
    return errors

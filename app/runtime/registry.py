"""Tool registry with explicit capability, state, resource and verification contracts.

V8 stays provider/model independent. A Tool is executable code plus a machine-readable
operator contract used by planning, policy, scheduling and verification.
"""
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, str]
    fn: Callable[..., Any]
    requires_approval: bool = False
    retries: int = 0
    stage: int = 0
    triggers: tuple[str, ...] = ()
    match: Callable[[str], bool] | None = None
    build_args: Callable[[str], dict] | None = None
    pipe_param: str | None = None
    pipe_source: bool = False
    pipe_label: Callable[[dict], str] | None = None
    # Planning/runtime contracts
    capability: str | None = None
    preconditions: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    removes: tuple[str, ...] = ()
    cost: float = 1.0
    duration: float = 0.0
    risk: str = "low"  # low | medium | high
    idempotent: bool = True
    parallel_safe: bool = False
    resource_costs: tuple[tuple[str, float], ...] = ()
    resources_required: tuple[str, ...] = ()
    exclusive_resources: tuple[str, ...] = ()
    verification_level: str = "standard"
    intent_priority: int = 0
    world_affordance: str | None = None
    emits_world_delta: bool = False
    # Explicit opt-in for Phase-8 safe exploration. This never grants execution authority.
    exploration_safe: bool = False
    # Decision-relevant information contract used to estimate the value of an information action.
    information_domains: tuple[str, ...] = ()
    information_gain_prior: float = 0.0
    # Organization metadata: the tool declares its bounded operational ownership.
    # Routing consumes this metadata; it never maps individual tool names to departments.
    organization_department: str | None = None
    organization_role: str | None = None
    # Optional explicit governance classification; when absent, governance derives it from the tool contract.
    governance_class: str | None = None

    def matches(self, goal: str) -> bool:
        # A custom matcher is authoritative: returning False must remain a hard negative.
        # This prevents broad semantic fallbacks from reviving intentionally excluded
        # tools (e.g. calculator inside a reminder or support-only operators).
        if self.match:
            return bool(self.match(goal))
        g = str(goal or "").lower()
        if self.triggers and any(t.casefold() in g for t in self.triggers):
            return True
        return self.name.lower() in g or (self.capability and self.capability.lower() in g)

    def args_for(self, goal: str) -> dict:
        return self.build_args(goal) if self.build_args else {}

    def validate_args(self, args: dict) -> list[str]:
        missing = [k for k in self.params if k not in args or args[k] in (None, "")]
        extra = [k for k in args if k not in self.params]
        errors = []
        if missing:
            errors.append(f"parameters ناقصة {missing}")
        if extra:
            errors.append(f"parameters زيادة {extra}")
        return errors

    def run(self, **kwargs) -> ToolResult:
        try:
            return ToolResult(ok=True, data=self.fn(**kwargs))
        except Exception as e:
            return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")

    def manifest(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "params": self.params,
            "requires_approval": self.requires_approval,
            "capability": self.capability or self.name,
            "preconditions": list(self.preconditions),
            "produces": list(self.produces),
            "removes": list(self.removes),
            "cost": self.cost,
            "duration": self.duration,
            "risk": self.risk,
            "idempotent": self.idempotent,
            "parallel_safe": self.parallel_safe,
            "resource_costs": dict(self.resource_costs),
            "resources_required": list(self.resources_required),
            "exclusive_resources": list(self.exclusive_resources),
            "verification_level": self.verification_level,
            "intent_priority": self.intent_priority,
            "world_affordance": self.world_affordance,
            "emits_world_delta": self.emits_world_delta,
            "exploration_safe": self.exploration_safe,
            "information_domains": list(self.information_domains),
            "information_gain_prior": self.information_gain_prior,
            "organization_department": self.organization_department,
            "organization_role": self.organization_role,
            "governance_class": self.governance_class,
        }


REGISTRY: dict[str, Tool] = {}


def register(t: Tool) -> Tool:
    if t.name in REGISTRY:
        raise ValueError(f"Tool مكررة: {t.name}")
    REGISTRY[t.name] = t
    return t


def tool(description: str, params: dict[str, str] | None = None, name: str | None = None, **opts):
    def wrap(fn):
        return register(Tool(name=name or fn.__name__, description=description,
                             params=params or {}, fn=fn, **opts))
    return wrap


def load_tools() -> dict[str, Tool]:
    import app.tools as pkg
    for m in pkgutil.walk_packages(pkg.__path__, prefix="app.tools."):
        importlib.import_module(m.name)
    return REGISTRY


def manifest() -> list[dict]:
    return [t.manifest() for t in load_tools().values()]

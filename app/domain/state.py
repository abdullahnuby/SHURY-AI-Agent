from dataclasses import dataclass, field
from typing import Any
import uuid
from app.domain.plan import Plan
from app.domain.world import WorldState


@dataclass
class AgentState:
    goal: str
    status: str = "started"
    max_steps: int = 6
    max_seconds: float = 30.0
    plan: Plan | None = None
    final_message: str = ""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    next_index: int = 0
    world: WorldState = field(default_factory=WorldState)
    outputs: dict = field(default_factory=dict)
    replans: int = 0
    checkpointed: bool = False
    semantic_parse: Any | None = None
    company_assignments: list[dict] = field(default_factory=list)
    company_coordination: dict = field(default_factory=dict)
    company_review: dict | None = None

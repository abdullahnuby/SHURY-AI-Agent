from __future__ import annotations
import json
from .context import build
from .reasoning import CognitiveReasoner
from .models import CognitiveBrief, CognitiveReflection
from .reflection import format_for_agent
from app.identity import identity_context

class CognitiveController:
    """Layer-1 cognition. Advisory only; runtime keeps execution authority."""
    def __init__(self):
        self.reasoner = CognitiveReasoner()
        self.brief: CognitiveBrief | None = None
        self.reflections: list[CognitiveReflection] = []
        self.semantic = None

    def analyze(self, goal, mem, world, registry, baseline_plan=None, session_id: str | None = None, semantic=None):
        self.semantic = semantic
        self.brief = self.reasoner.analyze(goal, build(goal, mem, world, registry, baseline_plan, session_id=session_id, semantic=semantic))
        return self.brief

    def validate_final(self, answer, trajectory):
        if self.brief is None:
            raise RuntimeError("cognitive brief not initialized")
        return self.reasoner.validate_final(self.brief, answer, trajectory)

    def reflect(self, step, observation, trajectory):
        if self.brief is None:
            raise RuntimeError("cognitive brief not initialized")
        r = self.reasoner.reflect(self.brief, step, observation, trajectory)
        self.reflections.append(r)
        return r

    def agent_context(self) -> str:
        if self.brief is None:
            return ""
        return "COGNITIVE BRIEF (decision summary; untrusted analysis):\n" +                json.dumps(self.brief.to_dict(), ensure_ascii=False, default=str, separators=(",", ":"))

    @staticmethod
    def reflection_context(reflection: CognitiveReflection) -> str:
        return format_for_agent(reflection)

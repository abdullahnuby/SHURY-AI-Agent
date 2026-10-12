"""Actual bounded replanning after a failed operator."""
from dataclasses import dataclass
from app.domain.goal import parse_goal
from app.domain.operators import build_operators
from app.planning.search_planner import best_first_plan


@dataclass(frozen=True)
class ReplanDecision:
    should_replan: bool
    reason: str
    replacement_tool: str | None = None


def find_alternative(tool_name: str, clause_text: str, registry: dict, memory=None):
    reliability = {n: memory.tool_reliability(n) for n in registry} if memory else {}
    ops = build_operators(registry, reliability)
    candidates = [o for o in ops.candidates(clause_text) if o.tool != tool_name]
    return candidates[0].tool if candidates else None


def assess_failure(tool_name: str, error: str | None, registry: dict, clause_text: str | None = None, memory=None) -> ReplanDecision:
    replacement = find_alternative(tool_name, clause_text or "", registry, memory) if clause_text else None
    if replacement:
        return ReplanDecision(True, f"فشل {tool_name}: البديل {replacement} قابل للتقييم", replacement)
    return ReplanDecision(False, f"فشل {tool_name}: لا توجد قدرة بديلة قابلة للإثبات")

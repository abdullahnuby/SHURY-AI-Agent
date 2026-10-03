"""Deterministic policy/guardrail layer. No model required."""
from dataclasses import dataclass

@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    approval_required: bool = False


def check_tool(tool, args: dict) -> PolicyDecision:
    risk = str(getattr(tool, "risk", "") or "").casefold()
    if risk in {"critical", "high"} and not bool(getattr(tool, "requires_approval", False)):
        return PolicyDecision(False, "high-risk tool must require explicit approval", True)
    if tool.requires_approval:
        return PolicyDecision(True, "write-side-effect", True)
    return PolicyDecision(True)

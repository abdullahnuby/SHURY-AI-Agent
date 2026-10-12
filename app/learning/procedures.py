from __future__ import annotations

import re
from typing import Any

from .diagnosis import task_signature, sanitize


def task_family_signature(goal: str) -> str:
    """Stable procedure-family identity; values/paths are slots, not task identity."""
    text = str(goal or "")
    text = re.sub(r"(?i)(api[_-]?key|token|password|secret|private[_-]?key)\s*[:=]\s*\S+", r"\1=<redacted>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", text)
    text = re.sub(r"[A-Za-z]:\\[^\s]+|/[^\s]+", "<path>", text)
    return task_signature(text)


def build_procedure_evidence(*, goal: str, operation: str, capability: str, steps: list[dict],
                             status: str, verified_rate: float, failure_class: str | None,
                             environment_signature: str, run_id: str) -> dict[str, Any]:
    workflow=[]
    trigger=[task_family_signature(goal)]
    termination=[]
    recovery=[]
    context=[]
    for step in steps:
        if not isinstance(step, dict) or not step.get("tool"):
            continue
        workflow.append({
            "tool": str(step.get("tool")),
            "capability": str(step.get("capability") or step.get("tool")),
            "depends_on": list(step.get("depends_on") or ()),
            "args_policy": "derive-from-live-goal",
        })
    if status == "completed" and verified_rate >= 0.80:
        termination.append("goal_verified")
    else:
        termination.append("goal_not_verified")
    if failure_class:
        recovery.append(f"replan_after:{failure_class}")
        termination.append(f"failure:{failure_class}")
    if environment_signature:
        context.append(f"environment:{environment_signature}")
    if operation:
        trigger.append(f"operation:{operation}")
    trigger.append(f"capability:{capability}")
    return {
        "task_family_signature": task_family_signature(goal),
        "operation": operation,
        "capability": capability,
        "workflow": workflow,
        "trigger_conditions": tuple(dict.fromkeys(trigger)),
        "termination_conditions": tuple(dict.fromkeys(termination)),
        "recovery_strategy": tuple(dict.fromkeys(recovery)),
        "context_boundary": tuple(dict.fromkeys(context)),
        "evidence_run_ids": (str(run_id),),
        "success": bool(status == "completed" and verified_rate >= 0.80),
        "confidence": min(0.95, max(0.20, 0.55 + 0.40 * float(verified_rate))) if workflow else 0.20,
    }


__all__ = ["task_family_signature", "build_procedure_evidence"]

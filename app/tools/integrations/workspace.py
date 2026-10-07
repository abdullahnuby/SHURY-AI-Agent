from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path
from app.knowledge.memory import get_memory
from app.services.workspace_service import workspace_analyze, compare_sources
import re
from pathlib import Path


def _extract_path(goal: str) -> str:
    from app.tools.workspace_reference import extract_workspace_reference, require_resolved_path
    result = extract_workspace_reference(goal, expected_kind="any", role="source")
    return require_resolved_path(result)


def _two_paths(goal: str) -> dict:
    quoted = re.findall(r'["\']([^"\']+)["\']', goal)
    if len(quoted) >= 2:
        return {"left": quoted[0], "right": quoted[1]}
    paths = re.findall(r'((?:[A-Za-z]:[\\/]|/)[^\s,]+)', goal)
    if len(paths) >= 2:
        return {"left": paths[-2], "right": paths[-1]}
    raise ValueError("أحتاج مسارين لمقارنة مصدرين؛ استخدم quotes حول كل مسار")

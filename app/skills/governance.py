"""Skill trust, admission, and lifecycle governance."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class SkillAdmission:
    allowed: bool
    trust: str
    reasons: tuple[str, ...]
    requires_approval: bool


def assess_skill(package_info: dict, *, source: str = "external") -> SkillAdmission:
    findings = package_info.get("security_findings", [])
    if not package_info.get("valid", False):
        return SkillAdmission(False, "invalid", ("schema validation failed",), True)
    severities = {f.get("severity") for f in findings}
    if "critical" in severities:
        return SkillAdmission(False, "blocked", ("critical security finding",), True)
    if "high" in severities:
        return SkillAdmission(True, "restricted", ("high-risk content requires explicit approval",), True)
    if source in {"external", "web", "github", "arxiv"}:
        return SkillAdmission(True, "quarantined", ("external skills must be validated before activation",), True)
    return SkillAdmission(True, "local", ("locally authored skill",), False)

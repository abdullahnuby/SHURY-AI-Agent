from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.skills.registry import SkillBank, SkillCandidate

from .catalog import OrganizationCatalog
from .evidence import SourceRegistry, SkillEvidencePolicy


@dataclass(frozen=True)
class OrganizationSkillBinding:
    """Runtime projection linking one existing SkillBank entry to the company roster.

    This is deliberately not a second Skill store. The SkillBank remains the single
    source of truth for skill lifecycle/content; the organization catalog owns only
    role/department assignment.
    """

    key: str
    name: str
    department: str
    roles: tuple[str, ...]
    capabilities: tuple[str, ...]
    outputs: tuple[str, ...]
    status: str
    trust_level: str
    confidence: float
    utility: float
    source: str
    verification: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]
    evidence_policy: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "department": self.department,
            "roles": list(self.roles),
            "capabilities": list(self.capabilities),
            "outputs": list(self.outputs),
            "status": self.status,
            "trust_level": self.trust_level,
            "confidence": self.confidence,
            "utility": self.utility,
            "source": self.source,
            "verification": list(self.verification),
            "evidence": list(self.evidence),
            "evidence_policy": dict(self.evidence_policy or {}),
        }


@dataclass(frozen=True)
class OrganizationSkillIndex:
    """Derived index from OrganizationCatalog + existing SkillBank."""

    catalog: OrganizationCatalog
    skill_bank: SkillBank

    def roles_for_skill(self, skill_key: str) -> tuple[str, ...]:
        key = str(skill_key or "").strip()
        return tuple(role.key for role in self.catalog.roles if key in role.skills)

    def departments_for_skill(self, skill_key: str) -> tuple[str, ...]:
        departments = sorted({role.department for role in self.catalog.roles if skill_key in role.skills and role.department})
        return tuple(departments)

    def skill(self, skill_key: str) -> OrganizationSkillBinding:
        skill = self.skill_bank.get(skill_key)
        roles = self.roles_for_skill(skill_key)
        departments = self.departments_for_skill(skill_key)
        if len(departments) > 1:
            raise ValueError(f"skill has multiple company department owners: {skill_key} -> {departments}")
        if not departments:
            raise KeyError(f"skill is not bound to the company roster: {skill_key}")
        capabilities = tuple(
            dict.fromkeys(
                str(item.get("capability", "")).strip()
                for item in skill.workflow
                if isinstance(item, dict) and str(item.get("capability", "")).strip()
            )
        )
        trust = self.skill_bank.trust(skill_key)
        evidence_policy = SourceRegistry().policy_for_skill(skill_key).to_dict()
        return OrganizationSkillBinding(
            key=skill.key,
            name=skill.name,
            department=departments[0],
            roles=roles,
            capabilities=capabilities,
            outputs=skill.outputs,
            status=skill.status,
            trust_level=trust,
            confidence=skill.confidence,
            utility=skill.utility,
            source=skill.source,
            verification=skill.verification,
            evidence=skill.evidence,
            evidence_policy=evidence_policy,
        )

    def skills_for_role(self, role_key: str, *, active_only: bool = True) -> tuple[OrganizationSkillBinding, ...]:
        role = next((r for r in self.catalog.roles if r.key == role_key), None)
        if role is None:
            raise KeyError(role_key)
        result: list[OrganizationSkillBinding] = []
        for key in role.skills:
            try:
                bound = self.skill(key)
            except KeyError:
                continue
            if active_only and bound.status not in {"approved", "active"}:
                continue
            result.append(bound)
        return tuple(result)

    def skills_for_department(self, department_key: str, *, active_only: bool = True) -> tuple[OrganizationSkillBinding, ...]:
        department = self.catalog.departments
        if not any(d.key == department_key for d in department):
            raise KeyError(department_key)
        keys: list[str] = []
        for role in self.catalog.roles:
            if role.department == department_key:
                keys.extend(role.skills)
        result: list[OrganizationSkillBinding] = []
        for key in dict.fromkeys(keys):
            try:
                bound = self.skill(key)
            except KeyError:
                continue
            if active_only and bound.status not in {"approved", "active"}:
                continue
            result.append(bound)
        return tuple(result)

    def skills_for_capability(self, capability: str, *, active_only: bool = True) -> tuple[OrganizationSkillBinding, ...]:
        key = str(capability or "").strip().casefold()
        if not key:
            return ()
        result: list[OrganizationSkillBinding] = []
        for role in self.catalog.roles:
            for skill_key in role.skills:
                try:
                    bound = self.skill(skill_key)
                except KeyError:
                    continue
                if active_only and bound.status not in {"approved", "active"}:
                    continue
                if any(cap.casefold() == key for cap in bound.capabilities):
                    result.append(bound)
        unique = {b.key: b for b in result}
        return tuple(sorted(unique.values(), key=lambda b: (-b.utility, -b.confidence, b.key)))

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        role_keys: dict[str, list[str]] = {}
        for role in self.catalog.roles:
            for key in role.skills:
                role_keys.setdefault(key, []).append(role.key)
                try:
                    self.skill_bank.get(key)
                except KeyError:
                    errors.append(f"missing_skill:{role.key}:{key}")
        for key, owners in role_keys.items():
            departments = {next(r.department for r in self.catalog.roles if r.key == role_key) for role_key in owners}
            if len(departments) > 1:
                errors.append(f"multi_department_skill:{key}:{sorted(departments)}")
        return tuple(dict.fromkeys(errors))

    def snapshot(self) -> dict[str, Any]:
        bindings: list[dict[str, Any]] = []
        for role in self.catalog.roles:
            for key in role.skills:
                if key in {b["key"] for b in bindings}:
                    continue
                try:
                    bindings.append(self.skill(key).to_dict())
                except KeyError:
                    pass
        return {
            "source_of_truth": "app.skills.registry.SkillBank",
            "organization_source": str(self.catalog.version),
            "binding_count": len(bindings),
            "bindings": bindings,
            "validation_errors": list(self.validate()),
        }

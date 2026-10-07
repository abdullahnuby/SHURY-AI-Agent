from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any

from .models import AgentRole, Department

DEFAULT_CATALOG_PATH = Path(__file__).with_name("organization.toml")


class OrganizationCatalogError(ValueError):
    """Raised when the declarative company catalog is invalid."""


@dataclass(frozen=True)
class OrganizationCatalog:
    name: str
    version: int
    principle: str
    ceo: AgentRole
    roles: tuple[AgentRole, ...]
    departments: tuple[Department, ...]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "OrganizationCatalog":
        catalog_path = Path(path or DEFAULT_CATALOG_PATH)
        with catalog_path.open("rb") as handle:
            raw = tomllib.load(handle)
        organization = raw.get("organization") or {}
        name = str(organization.get("name") or "SHURY Company").strip()
        try:
            version = int(organization.get("version", 1))
        except (TypeError, ValueError) as exc:
            raise OrganizationCatalogError("organization.version must be an integer") from exc
        principle = str(organization.get("principle") or "").strip()

        role_specs = tuple(raw.get("role") or ())
        department_specs = tuple(raw.get("department") or ())
        if not role_specs:
            raise OrganizationCatalogError("catalog must declare at least one role")
        if not department_specs:
            raise OrganizationCatalogError("catalog must declare at least one department")

        roles = tuple(cls._role_from_spec(spec) for spec in role_specs)
        departments = tuple(cls._department_from_spec(spec) for spec in department_specs)
        cls._validate(roles, departments)
        ceos = tuple(role for role in roles if role.agent_class == "orchestrator")
        if len(ceos) != 1:
            raise OrganizationCatalogError("catalog must declare exactly one orchestrator role")
        return cls(name, version, principle, ceos[0], roles, departments)

    @staticmethod
    def _as_tuple(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value.strip(),) if value.strip() else ()
        return tuple(str(item).strip() for item in value if str(item).strip())

    @classmethod
    def _role_from_spec(cls, spec: dict[str, Any]) -> AgentRole:
        key = str(spec.get("key") or "").strip()
        if not key:
            raise OrganizationCatalogError("role.key is required")
        parent_raw = str(spec.get("parent") or "").strip()
        return AgentRole(
            key=key,
            name=str(spec.get("name") or key).strip(),
            department=str(spec.get("department") or "").strip(),
            parent=parent_raw or None,
            agent_class=str(spec.get("agent_class") or "builder"),
            remit=str(spec.get("remit") or "").strip(),
            skills=cls._as_tuple(spec.get("skills")),
            capabilities=cls._as_tuple(spec.get("capabilities")),
            write_surfaces=cls._as_tuple(spec.get("write_surfaces")),
            runtime_domains=cls._as_tuple(spec.get("runtime_domains")),
            authority=str(spec.get("authority") or "autonomous"),
        )

    @classmethod
    def _department_from_spec(cls, spec: dict[str, Any]) -> Department:
        key = str(spec.get("key") or "").strip()
        if not key:
            raise OrganizationCatalogError("department.key is required")
        reviewer_raw = str(spec.get("reviewer") or "").strip()
        return Department(
            key=key,
            name=str(spec.get("name") or key).strip(),
            head_agent=str(spec.get("head_agent") or "").strip(),
            remit=str(spec.get("remit") or "").strip(),
            specialists=cls._as_tuple(spec.get("specialists")),
            reviewer=reviewer_raw or None,
            owned_capabilities=cls._as_tuple(spec.get("owned_capabilities")),
            owned_effects=cls._as_tuple(spec.get("owned_effects")),
        )

    @classmethod
    def _validate(cls, roles: tuple[AgentRole, ...], departments: tuple[Department, ...]) -> None:
        role_keys = [role.key for role in roles]
        department_keys = [department.key for department in departments]
        if len(role_keys) != len(set(role_keys)):
            raise OrganizationCatalogError("role keys must be unique")
        if len(department_keys) != len(set(department_keys)):
            raise OrganizationCatalogError("department keys must be unique")
        role_map = {role.key: role for role in roles}
        department_map = {department.key: department for department in departments}
        valid_classes = {'orchestrator', 'builder', 'reviewer'}
        valid_authorities = {'autonomous', 'proposes', 'escalates'}
        for role in roles:
            if role.agent_class not in valid_classes:
                raise OrganizationCatalogError(f'unknown agent class: {role.key} -> {role.agent_class}')
            if role.authority not in valid_authorities:
                raise OrganizationCatalogError(f'unknown role authority: {role.key} -> {role.authority}')
            if role.department not in department_map and role.agent_class != "orchestrator":
                raise OrganizationCatalogError(f"role department missing: {role.key} -> {role.department}")
            if role.parent and role.parent not in role_map:
                raise OrganizationCatalogError(f"role parent missing: {role.key} -> {role.parent}")
            if role.agent_class == "reviewer" and role.write_surfaces:
                raise OrganizationCatalogError(f"reviewer cannot own write surfaces: {role.key}")
        for department in departments:
            if department.head_agent not in role_map:
                raise OrganizationCatalogError(f"department head missing: {department.key} -> {department.head_agent}")
            if role_map[department.head_agent].department != department.key:
                raise OrganizationCatalogError(f"department head mismatch: {department.key} -> {department.head_agent}")
            for specialist in department.specialists:
                if specialist not in role_map:
                    raise OrganizationCatalogError(f"specialist missing: {department.key} -> {specialist}")
                if role_map[specialist].department != department.key:
                    raise OrganizationCatalogError(f"specialist department mismatch: {department.key} -> {specialist}")
            if department.reviewer:
                if department.reviewer not in role_map:
                    raise OrganizationCatalogError(f"reviewer missing: {department.key} -> {department.reviewer}")
                if role_map[department.reviewer].agent_class != "reviewer":
                    raise OrganizationCatalogError(f"department reviewer must be reviewer-class: {department.key}")

    def validate(self) -> tuple[str, ...]:
        try:
            self._validate(self.roles, self.departments)
        except OrganizationCatalogError as exc:
            return (str(exc),)
        return ()

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "principle": self.principle,
            "ceo": self.ceo.to_dict(),
            "roles": [role.to_dict() for role in self.roles],
            "departments": [department.to_dict() for department in self.departments],
        }

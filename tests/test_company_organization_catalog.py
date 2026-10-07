from pathlib import Path
import tomllib

import pytest

from app.organization import DEFAULT_COMPANY, OrganizationCatalog, OrganizationCatalogError
from app.organization.catalog import DEFAULT_CATALOG_PATH


def test_default_catalog_loads_and_matches_company():
    catalog = OrganizationCatalog.load()
    assert catalog.name == "SHURY Company"
    assert catalog.ceo.key == DEFAULT_COMPANY.ceo.key
    assert tuple(r.key for r in catalog.roles) == tuple(r.key for r in DEFAULT_COMPANY.roles)
    assert tuple(d.key for d in catalog.departments) == tuple(d.key for d in DEFAULT_COMPANY.departments)
    assert catalog.validate() == ()


def test_catalog_file_is_valid_toml():
    with Path(DEFAULT_CATALOG_PATH).open("rb") as handle:
        raw = tomllib.load(handle)
    assert raw["organization"]["name"] == "SHURY Company"
    assert len(raw["role"]) >= 1
    assert len(raw["department"]) >= 1


def test_catalog_has_exactly_one_orchestrator():
    catalog = OrganizationCatalog.load()
    orchestrators = [r for r in catalog.roles if r.agent_class == "orchestrator"]
    assert len(orchestrators) == 1
    assert orchestrators[0].write_surfaces == ()


def test_catalog_reviewer_roles_are_read_only():
    catalog = OrganizationCatalog.load()
    reviewers = [r for r in catalog.roles if r.agent_class == "reviewer"]
    assert reviewers
    assert all(r.write_surfaces == () for r in reviewers)
    assert all(r.read_only for r in reviewers)


def test_catalog_departments_have_valid_heads_and_specialists():
    catalog = OrganizationCatalog.load()
    roles = {r.key: r for r in catalog.roles}
    for department in catalog.departments:
        assert roles[department.head_agent].department == department.key
        for specialist in department.specialists:
            assert specialist in roles
            assert roles[specialist].department == department.key


def test_catalog_rejects_duplicate_role_keys(tmp_path):
    target = tmp_path / "organization.toml"
    target.write_text(
        """
[organization]
name = "x"
version = 1
principle = "x"

[[role]]
key = "ceo"
name = "CEO"
department = "executive"
agent_class = "orchestrator"
remit = "x"
write_surfaces = []

[[role]]
key = "ceo"
name = "Duplicate"
department = "executive"
agent_class = "builder"
remit = "x"

[[department]]
key = "executive"
name = "Executive"
head_agent = "ceo"
remit = "x"
specialists = []
""",
        encoding="utf-8",
    )
    with pytest.raises(OrganizationCatalogError, match="role keys must be unique"):
        OrganizationCatalog.load(target)


def test_catalog_rejects_missing_specialist(tmp_path):
    target = tmp_path / "organization.toml"
    target.write_text(
        """
[organization]
name = "x"
version = 1
principle = "x"

[[role]]
key = "ceo"
name = "CEO"
department = "executive"
agent_class = "orchestrator"
remit = "x"
write_surfaces = []

[[department]]
key = "executive"
name = "Executive"
head_agent = "ceo"
remit = "x"
specialists = ["missing"]
""",
        encoding="utf-8",
    )
    with pytest.raises(OrganizationCatalogError, match="specialist missing"):
        OrganizationCatalog.load(target)


def test_company_default_is_catalog_backed():
    assert DEFAULT_COMPANY.roles == OrganizationCatalog.load().roles
    assert DEFAULT_COMPANY.departments == OrganizationCatalog.load().departments

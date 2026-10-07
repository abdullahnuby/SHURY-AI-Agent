from pathlib import Path

from app.organization.catalog import OrganizationCatalog
from app.organization.skills import OrganizationSkillIndex
from app.skills.registry import SkillBank


def test_company_skill_index_uses_existing_skillbank(tmp_path):
    bank = SkillBank(tmp_path / "skills.db", bootstrap=True)
    catalog = OrganizationCatalog.load()
    index = OrganizationSkillIndex(catalog, bank)
    assert index.validate() == ()
    profile = index.skill("builtin:data-analysis")
    assert profile.department == "data"
    assert "data:data-analyst" in profile.roles
    assert "data_analysis" in profile.capabilities
    assert profile.status in {"active", "approved"}


def test_capability_lookup_is_derived_from_skill_workflows(tmp_path):
    bank = SkillBank(tmp_path / "skills.db", bootstrap=True)
    index = OrganizationSkillIndex(OrganizationCatalog.load(), bank)
    matches = index.skills_for_capability("data_analysis")
    assert matches
    assert matches[0].key == "builtin:data-analysis"


def test_missing_company_skill_fails_closed(tmp_path):
    bank = SkillBank(tmp_path / "skills.db", bootstrap=False)
    catalog = OrganizationCatalog.load()
    index = OrganizationSkillIndex(catalog, bank)
    errors = index.validate()
    assert any(error.startswith("missing_skill:") for error in errors)


def test_department_skill_set_contains_no_duplicate_bindings(tmp_path):
    bank = SkillBank(tmp_path / "skills.db", bootstrap=True)
    index = OrganizationSkillIndex(OrganizationCatalog.load(), bank)
    data = index.skills_for_department("data")
    keys = [skill.key for skill in data]
    assert len(keys) == len(set(keys))
    assert {"builtin:data-analysis", "builtin:data-analysis-report", "builtin:calculate"} <= set(keys)


def test_company_assignment_can_infer_skill_from_capability(tmp_path):
    from types import SimpleNamespace
    from app.organization import DEFAULT_COMPANY
    from app.runtime.registry import load_tools
    bank = SkillBank(tmp_path / "skills.db", bootstrap=True)
    # SkillBank is the runtime source of skill content; the company only resolves ownership.
    assert bank.get("builtin:data-analysis").status == "active"
    step = SimpleNamespace(
        step_id="s1", tool="analyze_dataset", capability="data_analysis",
        skill_key="", expected_effects=("analysis_evidence",), depends_on=()
    )
    assignment = DEFAULT_COMPANY.registry.build_assignment(
        objective="analyze a dataset", step=step, index=1, tool_registry=load_tools()
    )
    assert assignment.skill_key == "builtin:data-analysis"
    assert assignment.department == "data"
    assert assignment.specialist == "data:data-analyst"

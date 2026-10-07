from app.brain.models import PlannedAction
from app.organization import DEFAULT_COMPANY, ExecutiveTeamFormer
from app.runtime.registry import load_tools


def test_team_formation_uses_one_specialist_for_one_capability():
    plan = [PlannedAction("s1", "data_analysis", "analyze_dataset")]
    team = DEFAULT_COMPANY.form_team("analyze dataset", plan=plan, tool_registry=load_tools())
    assert team.valid is True
    assert team.specialist_count == 1
    assert team.departments == ("data",)
    assert team.members[0].role_key == "data:data-analyst"
    assert team.members[0].covered_capabilities == ("data_analysis",)


def test_team_formation_minimizes_specialists_when_one_role_covers_multiple_capabilities():
    plan = [
        PlannedAction("s1", "data_analysis", "analyze_dataset"),
        PlannedAction("s2", "calculate", "calculate", depends_on=("s1",)),
    ]
    team = DEFAULT_COMPANY.form_team("analyze and calculate", plan=plan, tool_registry=load_tools())
    assert team.valid is True
    assert team.specialist_count == 1
    assert team.departments == ("data",)
    assert team.members[0].role_key == "data:data-analyst"
    assert set(team.members[0].covered_capabilities) == {"data_analysis", "calculate"}


def test_team_formation_uses_only_justified_departments_for_cross_department_goal():
    plan = [
        PlannedAction("s1", "data_analysis", "analyze_dataset"),
        PlannedAction("s2", "file_read", "read_file", depends_on=("s1",)),
    ]
    team = DEFAULT_COMPANY.form_team("analyze then read", plan=plan, tool_registry=load_tools())
    assert team.valid is True
    assert team.specialist_count == 2
    assert set(team.departments) == {"data", "operations"}
    assert {m.role_key for m in team.members} == {"data:data-analyst", "operations:file-specialist"}


def test_team_formation_fails_closed_for_unresolved_requirement():
    from app.brain.models import SemanticFrame
    plan = DEFAULT_COMPANY.synthesize_capabilities("unknown",
        semantic=SemanticFrame(
            text="unknown", language="en", speech_act="command", concepts=(),
            requested_operation="totally_unknown_capability", uncertainty=(),
        ),
        tool_registry=load_tools(),
    )
    team = ExecutiveTeamFormer().form(
        objective="unknown", capability_plan=plan, organization=DEFAULT_COMPANY.registry,
        tool_registry=load_tools(),
    )
    assert team.valid is False
    assert team.uncovered == ("goal:1:totally_unknown_capability",)


def test_company_coordination_exposes_ceo_team_formation():
    plan = [
        PlannedAction("s1", "data_analysis", "analyze_dataset"),
        PlannedAction("s2", "file_read", "read_file", depends_on=("s1",)),
    ]
    coordination = DEFAULT_COMPANY.coordinate("analyze then read", plan, tool_registry=load_tools())
    formation = coordination.to_dict()["team_formation"]
    assert formation["valid"] is True
    assert formation["specialist_count"] == 2
    assert set(formation["departments"]) == {"data", "operations"}
    assert len(formation["members"]) == 2

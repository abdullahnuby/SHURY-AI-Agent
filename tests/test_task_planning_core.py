from app.domain.world import WorldState
from app.intelligence.semantic import semantic_understand
from app.intelligence.task_compiler import compile_task_ir
from app.planning.task_planner import plan_task_ir
from app.runtime.agent import plan_only
from app.runtime.registry import load_tools
from app.tools.data.analysis import profile_dataset_tool, analyze_dataset_tool
from app.skills.registry import SkillBank
from app.planning.adaptive_planning import skill_to_plan


def _plan(text):
    return plan_only(text)[0]


def test_release_readiness_expands_into_real_audit_method():
    plan = _plan("please check whether this project is ready for release")
    assert [s.tool for s in plan.steps] == ["inspect_project", "git_status", "check_project"]
    assert plan.diagnostics.get("task_ir_planner") is True
    assert plan.diagnostics["methods"][0]["method"] == "release_readiness_audit"
    assert plan.steps[1].depends_on == ["s1"]
    assert plan.steps[2].depends_on == ["s2"]


def test_list_skills_and_installed_remote_skills_are_distinct_capabilities():
    plan = _plan("list my skills and then show the installed skills")
    assert [s.tool for s in plan.steps] == ["list_skills", "installed_remote_skills"]
    assert plan.steps[1].depends_on == ["s1"]


def test_profile_then_analyze_uses_two_data_capabilities():
    plan = _plan("profile the dataset then analyze anomalies")
    assert [s.tool for s in plan.steps] == ["profile_dataset", "analyze_dataset"]
    assert plan.steps[1].depends_on == ["s1"]


def test_research_then_ground_uses_web_then_rag():
    plan = _plan("search the internet for recent agent memory research and retrieve evidence from the knowledge base")
    assert [s.tool for s in plan.steps] == ["web_research", "rag_query"]
    assert plan.steps[1].depends_on == ["s1"]
    assert any(item.get("method") == "research_then_ground" for item in plan.diagnostics["methods"])


def test_semantic_override_does_not_break_notes_or_recall():
    for text, tool in [
        ("سجل اجتماع 6-7", "save_note"),
        ("فاكر ايه عن اسم المشروع", "recall_fact"),
    ]:
        plan = _plan(text)
        assert [s.tool for s in plan.steps] == [tool]


def test_active_dataset_reference_resolves_deterministically(monkeypatch, tmp_path):
    dataset = tmp_path / "sales.csv"
    dataset.write_text(
        "date,amount\n2026-01-01,10\n2026-01-02,20\n2026-01-03,30\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    profile = profile_dataset_tool.fn(path="@active_dataset")
    assert profile["source"].endswith("sales.csv")
    analysis = analyze_dataset_tool.fn(path="@active_dataset", question="analyze anomalies in the dataset")
    assert analysis["verified"] is True


def test_active_dataset_reference_rejects_ambiguous_workspace(monkeypatch, tmp_path):
    for name in ("sales.csv", "costs.csv"):
        (tmp_path / name).write_text("id,value\n1,10\n2,20\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    try:
        profile_dataset_tool.fn(path="@active_dataset")
    except ValueError as exc:
        assert "أكثر من dataset" in str(exc)
    else:
        raise AssertionError("ambiguous active dataset should fail closed")


def test_verified_skill_matches_structural_task_across_paraphrase(tmp_path):
    bank = SkillBank(path=tmp_path / "skills.db")
    bank.upsert(
        key="auto:calculate-store",
        name="calculate then store result",
        triggers=("calculate", "save result"),
        workflow=(
            {"tool": "calculator", "depends_on": [], "capability": "calculate"},
            {"tool": "remember_result", "depends_on": ["s1"], "capability": "remember_result"},
        ),
        confidence=0.9,
        source="verified-runtime",
        status="active",
    )
    from app.intelligence.semantic import semantic_understand
    semantic = semantic_understand("work out 25*16 and remember the result as total", registry=load_tools())
    task_ir = compile_task_ir(semantic)
    matches = bank.match_task_ir(task_ir, limit=3)
    assert matches and matches[0].key == "auto:calculate-store"
    plan = skill_to_plan(matches[0], task_ir.original, load_tools(), task_ir=task_ir)
    assert plan is not None
    assert [s.tool for s in plan.steps] == ["calculator", "remember_result"]
    assert plan.steps[1].args["value"] == "{{s1}}"

import json
from pathlib import Path
from types import SimpleNamespace


def test_project_audit_semantic_structure_without_retrieval_model(monkeypatch):
    import app.intelligence.semantic.intents as intents
    intents.rank_query_against_texts = lambda text, rows, top_k=40: []
    from app.intelligence.semantic import semantic_understand
    text = (
        "افحص مشروع SHURY الحالي بالكامل. حدد نوع المشروع والـPython version والـdependencies الأساسية، "
        "افحص حالة Git الحالية، ثم شغّل الاختبارات المناسبة للمشروع. بعد ذلك حلل أي failures تظهر وحدد أهم 3 "
        "مشاكل حقيقية مرتبة حسب الأولوية مع ذكر الملف والسبب والدليل. أنشئ تقريرًا نهائيًا في "
        "workspace/shury_project_audit.md يحتوي على: project stack, dependencies, git status, test result, "
        "failures, root causes, priorities, recommendations. بعد إنشاء التقرير اقرأه مرة أخرى وتحقق من وجود "
        "الأقسام المطلوبة ومن أن البيانات الموجودة فيه مأخوذة من الفحص الفعلي للمشروع."
    )
    parsed = semantic_understand(text, mem=None, world=None, registry=None)
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == "project_audit"
    assert not parsed.needs_clarification


def test_project_audit_skill_expands_to_real_workflow(tmp_path):
    from app.skills.registry import SkillBank
    from app.runtime.registry import load_tools
    from app.brain.capabilities import discover_skill_candidates, discover_candidates
    from app.brain.models import SemanticFrame, GoalSpec, CognitiveState
    from app.brain.planner import plan

    bank = SkillBank(tmp_path / "skills.db", bootstrap=True)
    registry = load_tools()
    frame = SemanticFrame(
        text="audit project and create report",
        language="en", speech_act="command", concepts=("project_audit",),
        requested_operation="project_audit", slots=(), uncertainty=()
    )
    state = CognitiveState(user_text=frame.text, session_id="test-session", semantic=frame)
    state.goal = GoalSpec(
        name="audit_project", objective=frame.text,
        desired_state=("project_audit_report_created",),
        success_conditions=("project_audit_report_created",),
        required_capability="project_audit",
    )
    state.selected_skills = discover_skill_candidates(state.goal, frame, bank)
    state.selected_skill = state.selected_skills[0] if state.selected_skills else None
    actions = plan(state.goal, frame, discover_candidates(frame, registry), state=state, registry=registry, learning=None, experiences=None)
    assert state.selected_skill is not None
    assert state.selected_skill.key == "builtin:project-audit"
    assert [a.tool for a in actions] == ["inspect_project", "git_status", "audit_project_tests", "create_project_audit_report"]
    assert all(a.skill_key == "builtin:project-audit" for a in actions)
    assert actions[-1].args["test_audit"] == "{{s3}}"


def test_project_audit_report_tool_creates_verified_report(tmp_path, monkeypatch):
    from app.runtime.registry import load_tools
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "demo.py").write_text("print('ok')\n", encoding="utf-8")
    tools = load_tools()
    audit_result = tools["audit_project_tests"].run(path=".")
    assert audit_result.ok
    result_wrapped = tools["create_project_audit_report"].run(path=".", output_path="shury_project_audit.md", question="audit", test_audit=json.dumps(audit_result.data))
    assert result_wrapped.ok
    result = result_wrapped.data
    report = tmp_path / "shury_project_audit.md"
    assert result["verified"] is True
    assert report.is_file()
    content = report.read_text(encoding="utf-8")
    for section in ("## Project Stack", "## Dependencies", "## Git Status", "## Test Result", "## Failures", "## Root Causes", "## Priorities", "## Recommendations"):
        assert section in content


def test_audit_project_test_tool_verifies_even_when_a_test_fails(tmp_path, monkeypatch):
    from app.runtime.verify import verify_step
    from app.runtime.registry import load_tools
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path / "workspace"))
    (tmp_path / "workspace").mkdir()
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    tool = load_tools()["audit_project_tests"]
    wrapped = tool.run(path=".")
    assert wrapped.ok
    result = wrapped.data
    assert result["attempted"] >= 1
    assert result["failed"] >= 1
    assert wrapped.ok is True
    verified, error = verify_step(tool, {"path": "."}, wrapped)
    assert verified is True, error


def test_project_path_parser_does_not_treat_report_output_as_project_root():
    from app.tools.development.project import _path
    goal = ("افحص مشروع SHURY ثم أنشئ تقريرًا في "
            "workspace/shury_project_audit.md")
    assert _path(goal) == "."


def test_project_audit_output_path_comes_from_user_goal():
    from app.tools.development.audit import _output_path
    assert _output_path("create report in workspace/custom-audit.md") == "workspace/custom-audit.md"


def test_project_audit_semantic_boundary_survives_late_routing_adjustments(monkeypatch):
    import app.intelligence.semantic.intents as intents
    intents.rank_query_against_texts = lambda text, rows, top_k=40: [SimpleNamespace(name="open_world_learning::0", score=0.99, evidence=("adversarial-fuzzy",))]
    from app.intelligence.semantic import semantic_understand
    text = (
        "افحص مشروع SHURY بالكامل، راجع حالة Git، شغّل الاختبارات، حلل failures وحدد الأسباب الجذرية، "
        "ثم أنشئ تقريرًا في workspace/shury_project_audit.md."
    )
    parsed = semantic_understand(text, mem=None, world=None, registry=None)
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == "project_audit"
    assert parsed.top_intent.capability == "project_audit"
    assert not parsed.needs_clarification

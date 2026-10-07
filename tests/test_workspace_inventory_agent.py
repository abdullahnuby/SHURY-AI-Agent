from __future__ import annotations

from pathlib import Path


def _disable_retrieval(monkeypatch):
    import app.intelligence.semantic.intents as intents
    intents.rank_query_against_texts = lambda text, rows, top_k=40: []


def test_workspace_inventory_semantic_capability_is_unambiguous(monkeypatch):
    _disable_retrieval(monkeypatch)
    from app.intelligence.semantic import semantic_understand

    text = (
        "افحص مجلد workspace الحالي. احصر الملفات الموجودة فيه مع اسم كل ملف ونوعه وحجمه، "
        "ثم أنشئ ملفًا باسم workspace/file_inventory.md يحتوي على هذا الحصر في جدول منظم. "
        "بعد ذلك اقرأ الملف الذي أنشأته وتحقق من أن عدد الملفات فيه يطابق عدد الملفات التي وجدتها فعليًا."
    )
    parsed = semantic_understand(text, mem=None, world=None, registry=None)
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == "workspace_inventory"
    assert parsed.top_intent.capability == "workspace_inventory"
    assert parsed.needs_clarification is False
    assert "anaphoric_reference_unresolved" not in parsed.ambiguity_reasons


def test_workspace_inventory_skill_expands_to_three_real_steps(tmp_path):
    from app.skills.registry import SkillBank
    from app.runtime.registry import load_tools
    from app.brain.capabilities import discover_candidates, discover_skill_candidates
    from app.brain.models import CognitiveState, GoalSpec, SemanticFrame
    from app.brain.planner import make_goal, plan

    bank = SkillBank(tmp_path / "skills.db", bootstrap=True)
    registry = load_tools()
    frame = SemanticFrame(
        text="inventory the files in the workspace and create a report",
        language="en", speech_act="command", concepts=("workspace_inventory",),
        requested_operation="workspace_inventory", slots=(), uncertainty=(),
    )
    goal = make_goal(frame)
    state = CognitiveState(user_text=frame.text, session_id="s1", semantic=frame, goal=goal)
    selected = discover_skill_candidates(goal, frame, bank)
    assert selected and selected[0].key == "builtin:workspace-inventory"
    state.selected_skill = selected[0]
    candidates = discover_candidates(frame, registry)
    actions = plan(goal, frame, candidates, state=state, registry=registry, learning=None, experiences=None)
    assert [a.tool for a in actions] == ["list_files", "create_file_inventory", "read_file"]
    assert actions[1].depends_on == ("s1",)
    assert actions[2].args["path"] == "file_inventory.md"


def test_create_file_inventory_uses_snapshot_and_verifies(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "b.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    from app.runtime.registry import load_tools
    tools = load_tools()
    snapshot = tools["list_files"].run(path=".")
    assert snapshot.ok
    result = tools["create_file_inventory"].run(file_list=snapshot.data, output_path="file_inventory.md")
    assert result.ok
    assert result.data["verified"] is True
    assert result.data["file_count"] == len(snapshot.data)
    content = (tmp_path / "file_inventory.md").read_text(encoding="utf-8")
    assert "# Workspace File Inventory" in content
    assert "## Verification" in content


def test_workspace_inventory_without_retrieval_model_does_not_clarify(monkeypatch):
    _disable_retrieval(monkeypatch)
    from app.intelligence.semantic import semantic_understand

    parsed = semantic_understand(
        "list all files in the workspace and create a file inventory report",
        mem=None, world=None, registry=None,
    )
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == "workspace_inventory"
    assert parsed.needs_clarification is False

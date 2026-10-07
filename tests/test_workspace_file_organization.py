from __future__ import annotations

from pathlib import Path


def test_organization_moves_snapshot_files_without_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    (tmp_path / "photo.jpg").write_bytes(b"image")
    (tmp_path / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")
    (tmp_path / "mystery.xyz").write_text("unknown", encoding="utf-8")
    from app.runtime.registry import load_tools
    tools = load_tools()
    snapshot = tools["list_files"].run(path=".")
    assert snapshot.ok
    result = tools["organize_workspace_files"].run(file_list=snapshot.data, output_path="file_organization_report.md")
    assert result.ok, result.error
    data=result.data
    assert data["verified"] is True
    assert data["moved_file_count"] == 4
    assert data["verified_destination_count"] == 4
    assert data["all_fingerprints_match"] is True
    assert data["sources_cleared"] is True
    assert (tmp_path / "images" / "photo.jpg").read_bytes() == b"image"
    assert (tmp_path / "data" / "data.csv").exists()
    assert (tmp_path / "documents" / "notes.md").exists()
    assert (tmp_path / "other" / "mystery.xyz").exists()
    assert (tmp_path / "file_organization_report.md").exists()


def test_organization_uses_observed_snapshot_only(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    from app.runtime.registry import load_tools
    tools=load_tools()
    snapshot=tools["list_files"].run(path=".")
    (tmp_path / "late.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    result=tools["organize_workspace_files"].run(file_list=snapshot.data, output_path="report.md")
    assert result.ok, result.error
    assert (tmp_path / "documents" / "a.txt").exists()
    assert (tmp_path / "late.csv").exists()


def test_semantic_routes_file_organization_without_retrieval(monkeypatch):
    import app.intelligence.semantic.intents as intents
    intents.rank_query_against_texts=lambda text, rows, top_k=40: []
    from app.intelligence.semantic import semantic_understand
    parsed=semantic_understand(
        "افحص workspace ورتب الملفات حسب النوع وانقلها إلى مجلدات مناسبة ثم تحقق من النقل",
        mem=None, world=None, registry=None,
    )
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == "workspace_file_organization"
    assert parsed.needs_clarification is False


def test_organization_skill_expands_to_three_steps(tmp_path):
    from app.skills.registry import SkillBank
    from app.runtime.registry import load_tools
    from app.brain.capabilities import discover_candidates, discover_skill_candidates
    from app.brain.models import CognitiveState, SemanticFrame
    from app.brain.planner import make_goal, plan

    bank=SkillBank(tmp_path/"skills.db", bootstrap=True)
    registry=load_tools()
    frame=SemanticFrame(text="organize workspace files by type", language="en", speech_act="command", concepts=("workspace_file_organization",), requested_operation="workspace_file_organization", slots=(), uncertainty=())
    goal=make_goal(frame)
    state=CognitiveState(user_text=frame.text, session_id="s1", semantic=frame, goal=goal)
    selected=discover_skill_candidates(goal, frame, bank)
    assert selected and selected[0].key == "builtin:workspace-file-organization"
    state.selected_skill=selected[0]
    actions=discover_candidates(frame, registry)
    plan_actions=plan(goal, frame, actions, state=state, registry=registry, learning=None, experiences=None)
    assert [a.tool for a in plan_actions] == ["list_files", "organize_workspace_files", "read_file"]
    assert plan_actions[1].depends_on == ("s1",)
    assert plan_actions[2].depends_on == ("s2",)

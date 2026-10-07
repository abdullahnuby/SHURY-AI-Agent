from __future__ import annotations

from pathlib import Path


def test_level5_runs_through_canonical_cognitive_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AGENT_LEARNING_DB", str(tmp_path / "learning.db"))
    monkeypatch.setenv("AGENT_SKILLS_DB", str(tmp_path / "skills.db"))
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    workspace=Path(tmp_path / "workspace")
    workspace.mkdir(parents=True)
    (workspace / "photo.jpg").write_bytes(b"image")
    (workspace / "sales.csv").write_text("region,sales\nNorth,100\nSouth,50\n", encoding="utf-8")
    (workspace / "notes.md").write_text("hello", encoding="utf-8")
    from app.runtime.cognitive_agent import run_cognitive
    result=run_cognitive(
        "افحص workspace ورتب الملفات حسب النوع وانقلها إلى مجلدات مناسبة ثم أنشئ workspace/file_organization_report.md وتحقق من أن كل ملف مرصود تم نقله دون فقدان أو استبدال",
        approve=lambda tool,args: True, session_id="level5-live", max_steps=6,
    )
    assert result.status == "completed", result.final_message
    assert [s.tool for s in result.plan.steps] == ["list_files", "organize_workspace_files", "read_file"]
    assert all(s.status == "done" for s in result.plan.steps)
    assert (workspace / "images" / "photo.jpg").exists()
    assert (workspace / "data" / "sales.csv").exists()
    assert (workspace / "documents" / "notes.md").exists()
    assert (workspace / "file_organization_report.md").exists()

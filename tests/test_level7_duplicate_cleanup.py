from __future__ import annotations

from pathlib import Path


def _disable_retrieval(monkeypatch):
    import app.intelligence.semantic.intents as intents
    intents.rank_query_against_texts = lambda text, rows, top_k=40: []


GOAL = (
    "افحص مجلد workspace بالكامل بشكل recursive، وابحث عن الملفات التي لها نفس المحتوى الفعلي "
    "باستخدام بصمة المحتوى وليس الاسم أو المسار. حدّد مجموعات الملفات المتطابقة في المحتوى، "
    "واحتفظ بنسخة واحدة فقط من كل محتوى متطابق في مكانها الحالي، ثم أنشئ مجلد "
    "workspace/duplicates_archive وانقل إليه النسخ الزائدة فقط دون حذف أي ملف ودون استبدال أي ملف موجود. "
    "أنشئ تقريرًا باسم workspace/duplicate_cleanup_report.md يوضح لكل مجموعة: بصمة المحتوى، عدد النسخ، "
    "النسخة التي تم الاحتفاظ بها، والنسخ التي تم نقلها ومساراتها الجديدة، مع إجمالي عدد الملفات قبل وبعد العملية. "
    "بعد ذلك اقرأ التقرير مرة أخرى وتحقق من أن جميع الملفات المنقولة موجودة في الأرشيف، وأن بصماتها لم تتغير، "
    "وأن عدد المحتويات الفريدة قبل العملية يساوي عدد المحتويات الفريدة بعد العملية، وأن النسخة المحتفظ بها لكل مجموعة ما زالت موجودة، "
    "وألا يكون قد تم حذف أو استبدال أي ملف."
)


def test_level7_semantic_capability_is_selected(monkeypatch):
    _disable_retrieval(monkeypatch)
    from app.intelligence.semantic import semantic_understand
    parsed = semantic_understand(GOAL, mem=None, world=None, registry=None)
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == "workspace_duplicate_cleanup"
    assert parsed.top_intent.capability == "workspace_duplicate_cleanup"
    assert parsed.needs_clarification is False


def test_duplicate_cleanup_tool_preserves_unique_content_and_archives_extras(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path / "workspace"))
    root = tmp_path / "workspace"
    (root / "data").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "a.txt").write_text("same", encoding="utf-8")
    (root / "data" / "b.txt").write_text("same", encoding="utf-8")
    (root / "docs" / "c.txt").write_text("different", encoding="utf-8")
    from app.runtime.registry import load_tools
    tools = load_tools()
    snap = tools["list_files_recursive"].run(path=".", exclude_path="duplicate_cleanup_report.md")
    assert snap.ok
    result = tools["deduplicate_workspace_files"].run(file_list=snap.data)
    assert result.ok, result.error
    data = result.data
    assert data["verified"] is True
    assert data["report_reread_verified"] is True
    assert data["moved_file_count"] == 1
    assert data["final_file_count"] == 2
    assert data["workspace_managed_file_count_after"] == 3
    assert data["unique_content_count_preserved"] is True
    assert data["all_moved_fingerprints_match"] is True
    assert data["kept_copies_present"] is True
    assert (root / "duplicates_archive").is_dir()
    assert (root / "a.txt").exists()
    assert not (root / "data" / "b.txt").exists()
    archived = list((root / "duplicates_archive").iterdir())
    assert len(archived) == 1


def test_duplicate_cleanup_ignores_preexisting_archive_contents(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path / "workspace"))
    root = tmp_path / "workspace"
    (root / "duplicates_archive").mkdir(parents=True)
    (root / "a.txt").write_text("same", encoding="utf-8")
    (root / "data").mkdir(parents=True)
    (root / "data" / "b.txt").write_text("same", encoding="utf-8")
    (root / "duplicates_archive" / "legacy.txt").write_text("legacy", encoding="utf-8")
    from app.runtime.registry import load_tools
    tools = load_tools()
    snap = tools["list_files_recursive"].run(path=".", exclude_path="duplicate_cleanup_report.md")
    assert snap.ok
    result = tools["deduplicate_workspace_files"].run(file_list=snap.data)
    assert result.ok, result.error
    data = result.data
    assert data["verified"] is True
    assert data["moved_file_count"] == 1
    assert data["final_file_count"] == 1
    assert (root / "a.txt").exists()
    assert not (root / "data" / "b.txt").exists()
    assert (root / "duplicates_archive" / "legacy.txt").exists()


def test_level7_runs_through_canonical_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AGENT_LEARNING_DB", str(tmp_path / "learning.db"))
    monkeypatch.setenv("AGENT_SKILLS_DB", str(tmp_path / "skills.db"))
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    _disable_retrieval(monkeypatch)
    root = tmp_path / "workspace"
    (root / "data").mkdir(parents=True)
    (root / "a.txt").write_text("same", encoding="utf-8")
    (root / "data" / "b.txt").write_text("same", encoding="utf-8")
    (root / "data" / "c.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    from app.runtime.cognitive_agent import run_cognitive
    result = run_cognitive(GOAL, approve=lambda *a, **k: True, session_id="level7-live", max_steps=5)
    assert result.status == "completed", result.final_message
    assert [s.tool for s in result.plan.steps] == ["list_files_recursive", "deduplicate_workspace_files", "read_file"]
    assert (root / "duplicate_cleanup_report.md").exists()
    assert (root / "duplicates_archive").is_dir()


def test_legacy_inventory_result_does_not_satisfy_duplicate_capability():
    from app.runtime.verify import verify_step
    from app.runtime.registry import load_tools
    tools = load_tools()
    result = tools["create_file_inventory"].run(file_list=[], output_path="x.md")
    assert result.ok
    ok, _ = verify_step(tools["create_file_inventory"], {"output_path": "x.md"}, result)
    assert ok is True


def test_duplicate_cleanup_response_uses_actual_counts():
    from types import SimpleNamespace
    from app.brain.response import compose_action_result
    state = SimpleNamespace(semantic=SimpleNamespace(language='ar', requested_operation='workspace_duplicate_cleanup'), evidence=[])
    text = compose_action_result(state, action=None, output={"content": "report"}, all_outputs={
        "s2": {
            "duplicate_groups": [{"sha256": "a"}, {"sha256": "b"}],
            "duplicate_group_count": 2,
            "moved_file_count": 3,
            "archive": "duplicates_archive",
        },
        "s3": {"content": "report"},
    })
    assert "اكتشفت 2 مجموعات" in text
    assert "نقلت 3 نسخة" in text

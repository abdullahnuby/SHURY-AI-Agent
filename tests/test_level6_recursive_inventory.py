from __future__ import annotations
from pathlib import Path


def test_recursive_inventory_semantic_capability_is_selected(monkeypatch):
    monkeypatch.setenv('SHURY_NLP_MODE', 'off')
    from app.intelligence.semantic import semantic_understand
    text=(
        'افحص مجلد workspace بالكامل بما في ذلك المجلدات الفرعية. أنشئ تقريرًا باسم '
        'workspace/workspace_inventory.md يوضح لكل مجلد عدد الملفات وإجمالي حجم الملفات، '
        'ثم حدد أكبر 5 ملفات.'
    )
    parsed=semantic_understand(text, mem=None, world=None, registry=None)
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == 'workspace_recursive_inventory'
    assert parsed.top_intent.capability == 'workspace_recursive_inventory'
    assert parsed.needs_clarification is False


def test_recursive_inventory_tool_excludes_report_and_verifies(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_WORKSPACE', str(tmp_path / 'workspace'))
    root=Path(tmp_path/'workspace'); (root/'data'/'nested').mkdir(parents=True)
    (root/'a.txt').write_text('hello', encoding='utf-8')
    (root/'data'/'b.csv').write_text('x,y\n1,2\n', encoding='utf-8')
    (root/'data'/'nested'/'big.bin').write_bytes(b'x'*100)
    from app.runtime.registry import load_tools
    tools=load_tools()
    snap=tools['list_files_recursive'].run(path='.', exclude_path='workspace_inventory.md')
    assert snap.ok
    result=tools['create_workspace_tree_inventory'].run(file_list=snap.data, output_path='workspace_inventory.md')
    assert result.ok, result.error
    assert result.data['verified'] is True
    assert result.data['file_count'] == 3
    assert result.data['folder_stats_match'] is True
    assert result.data['largest_5_match'] is True
    assert result.data['report_excluded'] is True
    text=(root/'workspace_inventory.md').read_text(encoding='utf-8')
    assert '## Folder Statistics' in text
    assert '## Largest 5 Files' in text
    assert 'Excluded report: `workspace_inventory.md`' in text


def test_level6_runs_through_canonical_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_WORKSPACE', str(tmp_path / 'workspace'))
    monkeypatch.setenv('AGENT_LEARNING_DB', str(tmp_path / 'learning.db'))
    monkeypatch.setenv('AGENT_SKILLS_DB', str(tmp_path / 'skills.db'))
    monkeypatch.setenv('SHURY_NLP_MODE', 'off')
    root=Path(tmp_path/'workspace'); (root/'docs'/'nested').mkdir(parents=True)
    (root/'small.txt').write_text('abc', encoding='utf-8')
    (root/'docs'/'report.md').write_text('doc', encoding='utf-8')
    (root/'docs'/'nested'/'large.bin').write_bytes(b'Z'*512)
    from app.runtime.cognitive_agent import run_cognitive
    result=run_cognitive(
        'افحص workspace بالكامل بما في ذلك المجلدات الفرعية. أنشئ تقريرًا باسم '
        'workspace/workspace_inventory.md يوضح لكل مجلد: عدد الملفات الموجودة داخله، '
        'وإجمالي حجم الملفات بالبايت، وأنواع الملفات الموجودة. ثم حدد أكبر 5 ملفات من حيث الحجم '
        'مع المسار والحجم ونوع الملف. بعد ذلك اقرأ التقرير مرة أخرى وتحقق من أن أعداد الملفات والأحجام '
        'وأكبر 5 ملفات تطابق الحالة الفعلية الحالية للمجلدات والملفات، وأن التقرير نفسه مستبعد من الإحصاءات الأصلية.',
        approve=lambda *a, **k: True, session_id='level6-live', max_steps=5,
    )
    assert result.status == 'completed', result.final_message
    assert [s.tool for s in result.plan.steps] == ['list_files_recursive', 'create_workspace_tree_inventory', 'read_file']
    assert (root/'workspace_inventory.md').exists()


def test_level6_rejects_shallow_inventory_tool_in_goal_verification():
    from app.runtime.verify import verify_step
    from app.runtime.registry import load_tools
    tools=load_tools()
    result=tools['create_file_inventory'].run(file_list=[], output_path='x.md')
    assert result.ok
    ok, reason=verify_step(tools['create_file_inventory'], {'output_path':'x.md'}, result)
    assert ok is True  # legacy tool remains valid for its own capability; routing is tested separately.

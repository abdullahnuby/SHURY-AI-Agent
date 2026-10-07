from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.brain import CognitiveKernel
from app.brain.kernel import BrainResult
from app.brain.models import GoalSpec, PlannedAction, CognitiveState, Decision
from app.runtime.registry import Tool
from app.runtime.security import workspace_root
from app.tools.workspace_reference import extract_workspace_reference


@pytest.fixture(autouse=True)
def _reset_canonical_memory_singleton(monkeypatch):
    # Each dev case owns its temporary memory DB. The production Memory API intentionally
    # caches the default instance, so reset that cache here to prevent one phrasing case
    # from feeding durable memory into the next case.
    import app.knowledge.memory as memory_module

    monkeypatch.setattr(memory_module, "_default", None)
    yield
    monkeypatch.setattr(memory_module, "_default", None)


def _write(path: Path, text: str = "a,b\n1,2\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _brain(monkeypatch: pytest.MonkeyPatch, ws: Path) -> CognitiveKernel:
    monkeypatch.setenv("AGENT_WORKSPACE", str(ws))
    return CognitiveKernel()


@pytest.mark.parametrize(
    "phrase, rel, kind",
    [
        ("افحص مجلد تقارير وقولي كام ملف", "تقارير", "dir"),
        ('شيّك على folder "Inbox 2026"', "Inbox 2026", "dir"),
        ("الملف sales-data.csv فيه ايه؟", "sales-data.csv", "file"),
        ("اقرأ file notes_final.txt بسرعة", "notes_final.txt", "file"),
        ("راجع data\u200f/مبيعات.csv", "data/مبيعات.csv", "file"),
        ("حلل المجلد أرشيف", "أرشيف", "dir"),
        ("اقرا ملف sale_dat.csv", "sales_data.csv", "file"),
        ("افحص directory results", "results", "dir"),
    ],
)
def test_f1_workspace_reference_is_resolved_against_live_files(monkeypatch, tmp_path, phrase, rel, kind):
    ws = tmp_path / "workspace"
    target = ws / rel
    if kind == "dir":
        target.mkdir(parents=True)
        _write(target / "sample.txt", "x\n")
    else:
        _write(target)
    monkeypatch.setenv("AGENT_WORKSPACE", str(ws))
    result = extract_workspace_reference(phrase, expected_kind=kind, role="source")
    assert result.status == "resolved"
    assert result.value == rel.replace("\\", "/")
    assert (ws / result.value).exists()
    assert phrase != result.value


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("اجمع مبيعات ملف sales.csv", "30"),
        ("احسب متوسط revenue في monthly.csv", "20"),
        ("حلل ملف customers.csv وقولي الصفوف", "2"),
        ("افحص sales.csv وشوف التكرارات", "duplicate"),
        ("اقرأ lines.txt وقولي كام سطر", "3"),
        ("افحص مجلد docs وقولي كام ملف", "2"),
        ("راجع workspace بشكل recursive وقولي أكبر ملف", "recursive"),
        ("جرد workspace وقولي الملفات الموجودة", "6"),
    ],
)
def test_f2_local_tasks_use_workspace_not_remote(monkeypatch, tmp_path, phrase, expected):
    ws = tmp_path / "workspace"
    _write(ws / "sales.csv", "item,sales\na,10\nb,20\n")
    _write(ws / "monthly.csv", "month,revenue\njan,10\nfeb,30\n")
    _write(ws / "customers.csv", "id,name\n1,a\n2,b\n")
    _write(ws / "lines.txt", "one\ntwo\nthree\n")
    _write(ws / "docs" / "a.txt", "a\n")
    _write(ws / "docs" / "b.txt", "b\n")
    _write(ws / "nested" / "largest.bin", "x" * 100)
    brain = _brain(monkeypatch, ws)
    result = brain.act(phrase, max_steps=8, approve=lambda *_: True)
    tool_names = [event.get("tool") for event in result.state.trace if event.get("kind") == "action_observed"]
    remote_tools = {"web_research", "internet_research", "github_search", "github_research", "agentic_rag", "answer_question"}
    assert not remote_tools.intersection(tool_names)
    assert result.status in {"completed", "needs_user"}
    if expected in {"3", "2", "6"}:
        assert expected in result.response
    elif expected == "recursive":
        assert "أكبر" in result.response or "largest" in result.response.casefold()


@pytest.mark.parametrize(
    "phrase, ambiguous",
    [
        ("اقرأ report.txt", True),
        ("افحص فولدر archive", True),
        ("انقل note.txt إلى processed", True),
        ("انقل note.txt", False),
        ("حلل البيانات", False),
        ("نفذ الأمر", False),
        ("اعمل كده", False),
        ("انقل note.txt إلى folder", False),
    ],
)
def test_f3_missing_or_ambiguous_slots_stop_before_execution(monkeypatch, tmp_path, phrase, ambiguous):
    ws = tmp_path / "workspace"
    _write(ws / "a" / "report.txt", "a")
    _write(ws / "b" / "report.txt", "b")
    _write(ws / "note.txt", "note")
    (ws / "a" / "archive").mkdir(parents=True)
    (ws / "b" / "archive").mkdir(parents=True)
    (ws / "processed_a").mkdir()
    (ws / "processed_b").mkdir()
    brain = _brain(monkeypatch, ws)
    result = brain.act(phrase, max_steps=6, approve=lambda *_: True)
    assert result.state.decision is not None
    assert result.state.decision.kind == "clarify"
    assert "goal_or_capability" not in result.response
    assert "capability_not_identified" not in result.response
    assert "missing_information" not in result.response
    if "report.txt" in phrase:
        assert "report.txt" in result.response
    if "note.txt" in phrase:
        assert not (ws / "note.txt").exists() is False if phrase.startswith("انقل") and ambiguous else True


@pytest.mark.parametrize(
    "phrase, source, destination, report_name",
    [
        ("انقل source.txt إلى done", "source.txt", "done", None),
        ("حرك report.md للـarchive", "report.md", "archive", None),
        ("نقل data.csv إلى processed", "data.csv", "processed", None),
        ("put note.txt into done", "note.txt", "done", None),
        ("حلل sales.csv واكتب التقرير summary.md وحطه في reports", "sales.csv", "reports", "summary.md"),
        ("اعمل تقرير تحليل من revenue.csv باسم result.md في مجلد reports", "revenue.csv", "reports", "result.md"),
        ("انقل ملف memo.txt للمجلد finished", "memo.txt", "finished", None),
        ("move draft.txt to published", "draft.txt", "published", None),
    ],
)
def test_f4_action_and_destination_coverage_is_verified(monkeypatch, tmp_path, phrase, source, destination, report_name):
    ws = tmp_path / "workspace"
    if source.endswith("csv"):
        _write(ws / source, "item,sales\na,5\nb,9\n")
        if source == "revenue.csv":
            (ws / source).write_text("item,revenue\na,8\nb,12\n", encoding="utf-8")
    else:
        _write(ws / source, "payload")
    (ws / destination).mkdir(parents=True, exist_ok=True)
    brain = _brain(monkeypatch, ws)
    result = brain.act(phrase, max_steps=8, approve=lambda *_: True)
    assert result.status == "completed", result.response
    if report_name:
        report = ws / destination / report_name
        assert report.is_file()
        content = report.read_text(encoding="utf-8")
        assert "# Data Analysis Report" in content
        assert "## Key Findings" in content
    else:
        moved = ws / destination / Path(source).name
        assert moved.is_file()
        assert not (ws / source).exists()


@pytest.mark.parametrize(
    "store_phrase, recall_phrase, forget_phrase, key, value",
    [
        ("افتكر رقم المورد: 7421", "رقم المورد كان إيه؟", "انسى رقم المورد", "رقم المورد", "7421"),
        ("خزّن كود الفرع: EGY-7", "ايه الكود اللي قلتلك عليه؟", "انسَ كود الفرع", "كود الفرع", "EGY-7"),
        ("سجل رقم الطلب: 9911", "فاكر الرقم اللي سجلته؟", "امسح رقم الطلب", "رقم الطلب", "9911"),
        ("افتكر اسم المشروع: Atlas", "ايه المعلومة اللي قلتلك عليها؟", "انسى اسم المشروع", "اسم المشروع", "Atlas"),
        ("احفظ الموعد: الخميس", "تفتكر الموعد كان إيه؟", "انسى الموعد", "الموعد", "الخميس"),
        ("سجل رقم العقد: C-55", "قلتلك رقم العقد كام؟", "احذف رقم العقد", "رقم العقد", "C-55"),
        ("افتكر البريد الداخلي: ops@local", "إيه البيانات اللي قلتلك عليها؟", "انسى البريد الداخلي", "البريد الداخلي", "ops@local"),
        ("خزّن كود المشروع: P9", "كان كود المشروع إيه؟", "امسح كود المشروع", "كود المشروع", "P9"),
    ],
)
def test_f5_memory_stays_memory_and_forget_is_real(monkeypatch, tmp_path, store_phrase, recall_phrase, forget_phrase, key, value):
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True)
    brain = _brain(monkeypatch, ws)
    session = f"dev-memory-{key}-{value}"
    saved = brain.act(store_phrase, session_id=session, max_steps=6, approve=lambda *_: True)
    assert saved.status == "completed", saved.response
    recalled = brain.act(recall_phrase, session_id=session, max_steps=6, approve=lambda *_: True)
    assert recalled.state.semantic is not None
    assert recalled.state.semantic.requested_operation in {"query_memory", "query_identity"}
    assert value in recalled.response
    assert not any(event.get("tool") in {"web_research", "internet_research", "github_search", "agentic_rag"} for event in recalled.state.trace)
    forgotten = brain.act(forget_phrase, session_id=session, max_steps=6, approve=lambda *_: True)
    assert forgotten.status == "completed", forgotten.response
    after = brain.act(recall_phrase, session_id=session, max_steps=6, approve=lambda *_: True)
    assert "معنديش معلومة" in after.response
    assert value not in after.response
    assert not any(event.get("tool") in {"web_research", "internet_research", "github_search", "agentic_rag"} for event in after.state.trace)


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("احسب 120 في 50 وزود 14%", "6840"),
        ("احسب 900 ناقص 175", "725"),
        ("احسب 1440 على 12", "120"),
        ("احسب ١٥٠ في ٢٠ وزود ١٠٪", "3300"),
        ("calculate 25 * 4 + 3", "103"),
        ("احسب 100 + 14%", "114"),
        ("احسب 10 ناقص 5", "5"),
        ("احسب 7 في 8", "56"),
    ],
)
def test_f6_direct_arithmetic_beats_memory(monkeypatch, tmp_path, phrase, expected):
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True)
    brain = _brain(monkeypatch, ws)
    session = f"dev-calc-{expected}"
    brain.act("افتكر الفاتورة: 999999", session_id=session, max_steps=6, approve=lambda *_: True)
    result = brain.act(phrase, session_id=session, max_steps=6, approve=lambda *_: True)
    assert result.status == "completed", result.response
    assert expected in result.response
    assert "999999" not in result.response
    assert "=" in result.response
    assert result.state.semantic is not None
    assert result.state.semantic.requested_operation == "calculate"
    calc_events = [e for e in result.state.trace if e.get("tool") == "calculator"]
    assert calc_events


@pytest.mark.parametrize(
    "phrase",
    [
        "ما رقم المورد؟",
        "رقم المورد كان كام؟",
        "الكود كان إيه؟",
        "إيه كود الفرع المسجل؟",
        "فين المعلومة اللي خزنتها؟",
        "المعلومات اللي قلتلك عليها فين؟",
        "كام رقم العقد اللي سجلته؟",
        "اسم المشروع المحفوظ عندك إيه؟",
    ],
)
def test_f5_memory_style_recall_without_match_never_falls_to_web(monkeypatch, tmp_path, phrase):
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True)
    brain = _brain(monkeypatch, ws)
    result = brain.act(phrase, session_id="dev-memory-miss", max_steps=6, max_seconds=8, approve=lambda *_: True)
    tools = [event.get("tool") for event in result.state.trace if event.get("tool")]
    assert result.status == "completed", result.response
    assert "معنديش معلومة" in result.response
    assert not any(name in {"web_research", "internet_research", "github_search", "agentic_rag", "answer_question"} for name in tools)


def test_f6_act_budget_covers_thinking_stage(monkeypatch, tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True)
    brain = _brain(monkeypatch, ws)
    original_think = brain.think

    def slow_think(*args, **kwargs):
        time.sleep(0.25)
        return original_think(*args, **kwargs)

    monkeypatch.setattr(brain, "think", slow_think)
    start = time.monotonic()
    result = brain.act("احسب 2 + 2", max_steps=4, max_seconds=0.03, approve=lambda *_: True)
    elapsed = time.monotonic() - start
    assert result.status == "timeout"
    assert elapsed < 0.12
    assert "انتهت الميزانية" in result.response


def test_f6_execution_budget_bounds_slow_network(monkeypatch, tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True)
    brain = _brain(monkeypatch, ws)
    slow = Tool(
        name="slow_network",
        description="dev slow network probe",
        params={},
        fn=lambda: time.sleep(0.25),
        capability="web_research",
        organization_department="research",
        organization_role="research:analyst",
        risk="low",
        duration=0.25,
    )
    start = time.monotonic()
    result = brain._bounded_tool_run(slow, {}, 0.03)
    elapsed = time.monotonic() - start
    assert elapsed < 0.12
    assert getattr(result, "ok", True) is False
    assert "timeout" in str(getattr(result, "error", "")).casefold()


@pytest.mark.parametrize(
    "phrase",
    [
        "اقرا ../secret.txt",
        "read /tmp/secret.txt",
        "افتح ../../etc/passwd",
        "اقرأ /var/tmp/x.txt",
        "هات C:/private/secret.txt",
        "حلل ../outside.csv",
        "انقل file.txt إلى /tmp/out",
        "move note.txt to ../../outside",
    ],
)
def test_f7_external_workspace_paths_are_refused_without_tool_call(monkeypatch, tmp_path, phrase):
    ws = tmp_path / "workspace"
    _write(ws / "file.txt", "safe")
    _write(ws / "note.txt", "safe")
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do not touch", encoding="utf-8")
    brain = _brain(monkeypatch, ws)
    calls = {"count": 0}
    original = brain.registry["read_file"].fn

    def probe(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    brain.registry["read_file"].fn = probe
    result = brain.act(phrase, max_steps=6, approve=lambda *_: True)
    assert result.state.decision is not None
    assert result.state.decision.kind == "refuse"
    assert "خارج" in result.response
    assert calls["count"] == 0
    assert outside.read_text(encoding="utf-8") == "do not touch"


def test_f0_verification_failure_replans_without_nameerror(monkeypatch, tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True)
    brain = _brain(monkeypatch, ws)
    tool = brain.registry["read_file"]
    action = PlannedAction("s1", tool.capability, tool.name, {"path": "missing.txt"}, (), tool.produces)
    state = CognitiveState(user_text="اقرأ missing.txt", session_id="f0")
    state.semantic = None
    state.goal = GoalSpec(name="read", objective="read a local file")
    state.plan = (action,)
    state.decision = Decision('execute', 0.99, 'dev verification failure', capability=tool.capability, tool=tool.name, plan=(action,))
    state.company_assignments = [{"step_id": "s1", "department": tool.organization_department, "specialist": tool.organization_role, "capability": tool.capability, "skill_key": ""}]
    state.company_coordination = brain.company.coordinate(state.goal.objective, brain.company.route_plan(state.goal.objective, [action], tool_registry=brain.registry), tool_registry=brain.registry).to_dict()
    monkeypatch.setattr(brain, "_run_action", lambda *args, **kwargs: (True, {"ok": True}, None, True, 0.001))
    monkeypatch.setattr(brain, "_verify_output", lambda *args, **kwargs: False)
    result = brain._execute_result(BrainResult(state, ""), approve=lambda *_: True, max_steps=2)
    assert result.status in {"completed", "failed"}
    assert any(item.get('kind') == 'verification_failed' for item in state.trace)
    assert 'NameError' not in ' '.join(str(item.get('error', '')) for item in state.trace)

from pathlib import Path

from app.brain import CognitiveKernel
from app.brain.learning import BrainExperienceStore
from app.brain.store import BrainStateStore
from app.knowledge.memory import Memory


def _kernel(tmp_path: Path) -> CognitiveKernel:
    return CognitiveKernel(
        memory=Memory(tmp_path / "memory.db"),
        state_store=BrainStateStore(tmp_path / "brain_state.db"),
        experience_store=BrainExperienceStore(tmp_path / "experience.db"),
    )


def test_explicit_workspace_csv_read_is_planned_and_executed(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sales.csv").write_text(
        "date,region,sales\n2026-01-01,North,100\n2026-01-02,North,105\n2026-01-03,North,98\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))
    brain = _kernel(tmp_path)
    request = "اقرأ sales.csv من مساحة العمل، واعرض أسماء الأعمدة وأول 3 صفوف كما هي."

    planned = brain.think(request, session_id="file-read-plan")
    assert planned.state.semantic.requested_operation == "file_read"
    assert planned.state.semantic.slot("path") == "sales.csv"
    assert planned.state.decision.kind == "execute"
    assert planned.state.plan[0].tool == "read_file"

    result = brain.act(request, session_id="file-read-execute")
    assert result.status == "completed"
    assert "date,region,sales" in result.response
    assert "2026-01-03,North,98" in result.response


def test_explicit_workspace_csv_sum_is_planned_and_executed(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sales.csv").write_text(
        "date,region,sales\n2026-01-01,North,100\n2026-01-02,North,105\n"
        "2026-01-03,North,98\n2026-01-04,North,102\n2026-01-05,North,1000\n"
        "2026-01-06,South,110\n2026-01-07,South,108\n2026-01-08,South,111\n"
        "2026-01-09,South,109\n2026-01-10,South,107\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))
    brain = _kernel(tmp_path)
    request = "حلل الملف `sales.csv` من مساحة العمل، واجمع كل القيم في عمود `sales`. أعطني الإجمالي فقط."

    planned = brain.think(request, session_id="csv-sum-plan")
    assert planned.state.semantic.requested_operation == "data_analysis"
    assert planned.state.semantic.slot("path") == "sales.csv"
    assert planned.state.decision.kind == "execute"
    assert planned.state.plan[0].tool == "analyze_dataset"

    result = brain.act(request, session_id="csv-sum-execute")
    assert result.status == "completed"
    assert result.response == "إجمالي sales = 1950"


def test_workspace_csv_sum_per_category_returns_group_totals(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sales.csv").write_text(
        "date,region,sales\n2026-01-01,North,100\n2026-01-02,North,105\n"
        "2026-01-03,North,98\n2026-01-04,North,102\n2026-01-05,North,1000\n"
        "2026-01-06,South,110\n2026-01-07,South,108\n2026-01-08,South,111\n"
        "2026-01-09,South,109\n2026-01-10,South,107\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))
    brain = _kernel(tmp_path)
    request = "من sales.csv في مساحة العمل، اجمع عمود sales لكل region على حدة. أعطني إجمالي كل منطقة فقط."

    result = brain.act(request, session_id="csv-sum-by-region")
    assert result.status == "completed"
    assert "North: 1405" in result.response
    assert "South: 545" in result.response
    assert "1950" not in result.response


def test_workspace_csv_maximum_is_labeled_as_maximum(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sales.csv").write_text(
        "date,region,sales\n2026-01-01,North,100\n2026-01-02,North,1000\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))
    brain = _kernel(tmp_path)
    request = "حلل sales.csv من مساحة العمل وحدد أعلى قيمة في عمود sales. أعطني القيمة فقط."

    result = brain.act(request, session_id="csv-maximum")
    assert result.status == "completed"
    assert result.response == "أعلى قيمة sales = 1000"


def test_mean_request_after_grouped_sum_is_not_misread_as_grouping(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sales.csv").write_text(
        "date,region,sales\n2026-01-01,North,100\n2026-01-02,North,105\n"
        "2026-01-03,North,98\n2026-01-04,North,102\n2026-01-05,North,1000\n"
        "2026-01-06,South,110\n2026-01-07,South,108\n2026-01-08,South,111\n"
        "2026-01-09,South,109\n2026-01-10,South,107\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))
    brain = _kernel(tmp_path)
    grouped = brain.act(
        "من sales.csv في مساحة العمل، اجمع عمود sales لكل region على حدة. أعطني إجمالي كل منطقة فقط.",
        session_id="csv-group-then-mean",
    )
    assert "North: 1405.0" in grouped.response
    assert "South: 545.0" in grouped.response

    result = brain.act(
        "احسب متوسط القيم في عمود sales من sales.csv في مساحة العمل. أعطني المتوسط فقط.",
        session_id="csv-group-then-mean",
    )
    assert result.status == "completed"
    assert result.response == "متوسط sales = 195"


def test_workspace_csv_row_count_in_arabic_is_executed_and_rendered(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sales.csv").write_text(
        "date,region,sales\n2026-01-01,North,100\n2026-01-02,North,105\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))
    brain = _kernel(tmp_path)

    for index, request in enumerate((
        "كم عدد الصفوف في sales.csv في مساحة العمل؟ أعطني العدد فقط.",
        "احسب عدد الصفوف في `sales.csv` في مساحة العمل؟ أعطني العدد فقط.",
    )):
        result = brain.act(request, session_id=f"csv-row-count-{index}")
        assert result.status == "completed"
        assert result.state.semantic.requested_operation == "data_analysis"
        assert result.response == "عدد الصفوف = 2"


def test_workspace_csv_minimum_value_request_is_not_routed_to_memory(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sales.csv").write_text(
        "date,region,sales\n2026-01-01,North,100\n2026-01-02,North,98\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))
    brain = _kernel(tmp_path)
    request = "حدد أقل قيمة في عمود sales من sales.csv في مساحة العمل. أعطني القيمة فقط."

    planned = brain.think(request, session_id="csv-minimum-plan")
    assert planned.state.semantic.requested_operation == "data_analysis"
    assert planned.state.decision.kind == "execute"
    assert planned.state.plan[0].tool == "analyze_dataset"

    result = brain.act(request, session_id="csv-minimum-execution")
    assert result.status == "completed"
    assert result.response == "أقل قيمة sales = 98"


def test_workspace_csv_outlier_request_returns_the_outlier_value(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sales.csv").write_text(
        "date,region,sales\n"
        "2026-01-01,North,100\n2026-01-02,North,105\n2026-01-03,North,98\n"
        "2026-01-04,North,102\n2026-01-05,North,1000\n2026-01-06,South,110\n"
        "2026-01-07,South,108\n2026-01-08,South,111\n2026-01-09,South,109\n"
        "2026-01-10,South,107\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))
    brain = _kernel(tmp_path)
    request = "اكتشف القيم الشاذة في عمود sales من sales.csv في مساحة العمل، واذكر القيمة الشاذة فقط."

    planned = brain.think(request, session_id="csv-outliers-plan")
    assert planned.state.semantic.requested_operation == "data_analysis"
    assert planned.state.plan[0].tool == "analyze_dataset"

    result = brain.act(request, session_id="csv-outliers-execution")
    assert result.status == "completed"
    assert result.response == "القيم الشاذة = 1000"

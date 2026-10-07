from pathlib import Path


def test_report_executes_and_verifies_requested_metrics_against_source(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sales.csv").write_text(
        "date,region,sales\n"
        "2026-01-01,Cairo,100\n"
        "2026-01-02,Cairo,120\n"
        "2026-01-03,Alex,1000\n"
        "2026-01-04,Alex,98\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))

    from app.tools.data.analysis import create_data_analysis_report

    result = create_data_analysis_report.run(
        path="sales.csv",
        output_path="sales_insights.md",
        question=(
            "حدد عمود المبيعات أو الإيراد إن كان موجودًا، ثم احسب إجمالي المبيعات ومتوسطها "
            "وأعلى قيمة وأقل قيمة، وحدد الصف الذي يحتوي على أعلى قيمة."
        ),
    )

    assert result.ok is True
    assert result.data["verified"] is True
    assert result.data["goal_verification"]["ok"] is True
    metrics = result.data["requested_metrics"]
    assert metrics["selected_column"] == "sales"
    assert metrics["total"] == 1318.0
    assert metrics["average"] == 329.5
    assert metrics["maximum"] == 1000.0
    assert metrics["minimum"] == 98.0
    assert metrics["max_row"]["data_row"] == 3
    assert metrics["max_row"]["record"]["region"] == "Alex"

    report = (workspace / "sales_insights.md").read_text(encoding="utf-8")
    assert "## Requested Metrics" in report
    assert "Total: **1318**" in report
    assert "Average: **329.5**" in report
    assert "Maximum: **1000**" in report
    assert "Minimum: **98**" in report
    assert "Row with maximum: data row **3**" in report
    assert result.data["goal_verification"]["checks"]["certificate_equals_recomputed_source"] is True


def test_report_fails_closed_when_requested_numeric_column_is_ambiguous(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "data.csv").write_text(
        "a,b,label\n1,10,x\n2,20,y\n3,30,z\n4,40,w\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))

    from app.tools.data.analysis import create_data_analysis_report

    result = create_data_analysis_report.run(
        path="data.csv",
        output_path="out.md",
        question="احسب إجمالي المبيعات ومتوسطها وأعلى قيمة وأقل قيمة والصف صاحب أعلى قيمة.",
    )

    assert result.ok is True
    assert result.data["verified"] is False
    assert result.data["goal_verification"]["ok"] is False

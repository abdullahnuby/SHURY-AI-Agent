from pathlib import Path


def test_report_executes_group_comparison_decision_and_verifies_against_source(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sales.csv").write_text(
        "date,region,sales,channel\n"
        "2026-01-01,North,100,Direct\n"
        "2026-01-02,South,80,Online\n"
        "2026-01-03,North,140,Online\n"
        "2026-01-04,East,60,Direct\n"
        "2026-01-05,South,90,Direct\n"
        "2026-01-06,East,70,Online\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKSPACE", str(workspace))

    from app.tools.data.analysis import create_data_analysis_report

    question = (
        "قارن إجمالي المبيعات بين المناطق الموجودة في البيانات وحدد المنطقة صاحبة أعلى إجمالي مبيعات "
        "والمنطقة صاحبة أقل إجمالي. ثم أنشئ ملفًا باسم workspace/sales_decision.md يحتوي على: "
        "إجمالي مبيعات كل منطقة، المنطقة الأعلى، المنطقة الأقل، والقرار العملي الذي تقترحه بناءً على هذه البيانات فقط. "
        "بعد ذلك اقرأ الملف الذي أنشأته وقارن الأرقام والقرار بالبيانات الأصلية وتحقق من أن كل نتيجة في التقرير مدعومة بالبيانات."
    )

    result = create_data_analysis_report.run(
        path="sales.csv",
        output_path="sales_decision.md",
        question=question,
    )

    assert result.ok is True
    assert result.data["verified"] is True
    assert result.data["goal_verification"]["ok"] is True

    comparison = result.data["group_comparison"]
    assert comparison["group_by"] == "region"
    assert comparison["value_column"] == "sales"
    assert {x["group"]: x["total"] for x in comparison["groups"]} == {
        "North": 240.0,
        "South": 170.0,
        "East": 130.0,
    }
    assert comparison["highest_total_group"]["group"] == "North"
    assert comparison["lowest_total_group"]["group"] == "East"
    assert comparison["total_spread"] == 110.0
    assert comparison["verified_against_source"] is True

    report = (workspace / "sales_decision.md").read_text(encoding="utf-8")
    assert "## Group Comparison" in report
    assert "| North | 2 | 240 |" in report
    assert "| South | 2 | 170 |" in report
    assert "| East | 2 | 130 |" in report
    assert "Highest total: **North** = **240**" in report
    assert "Lowest total: **East** = **130**" in report
    assert "### Decision" in report
    assert "## Group Comparison Certificate" in report
    assert result.data["goal_verification"]["checks"]["group_comparison"]["checks"]["certificate_equals_recomputed_source"] is True

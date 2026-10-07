from pathlib import Path


def test_real_data_analysis_report_tool_creates_and_verifies_artifact(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'sales.csv').write_text(
        'amount,region,customer\n10,A,alpha\n20,B,beta\n30,A,alpha\n1000,B,gamma\n20,B,beta\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('AGENT_WORKSPACE', str(workspace))
    from app.tools.data.analysis import create_data_analysis_report

    result = create_data_analysis_report.run(
        path='sales.csv',
        output_path='sales_report.md',
        question='Analyze schema, missing values, duplicates, outliers, and important patterns.',
    )
    assert result.ok is True
    assert result.data['verified'] is True
    report = workspace / 'sales_report.md'
    assert report.is_file()
    content = report.read_text(encoding='utf-8')
    assert '# Data Analysis Report' in content
    assert '## Schema and Column Statistics' in content
    assert '## Key Findings' in content
    assert 'sales.csv' in content

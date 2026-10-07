from pathlib import Path

from app.runtime.security import safe_workspace_path, workspace_root


def test_workspace_prefixed_relative_path_is_not_double_prefixed(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    target = safe_workspace_path("workspace/sales.csv")
    assert target == (tmp_path / "sales.csv").resolve()


def test_normal_relative_path_stays_inside_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    target = safe_workspace_path("reports/sales.md")
    assert target == (tmp_path / "reports" / "sales.md").resolve()
    assert workspace_root() == tmp_path.resolve()

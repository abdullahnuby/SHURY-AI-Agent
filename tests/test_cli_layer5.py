from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import app.interfaces.cli as cli

def test_layer5_cli_dispatch_status(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_LEARNING_DB", str(tmp_path / "learning.db"))
    monkeypatch.setenv("AGENT_SKILLS_DB", str(tmp_path / "skills.db"))
    inputs = iter(["/learning-status", "exit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    cli.main()
    out = capsys.readouterr().out
    assert '"experiences"' in out
    assert '"skills"' in out

def test_layer5_cli_dispatch_benchmark(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    inputs = iter(["/self-improvement-benchmark", "exit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    cli.main()
    out = capsys.readouterr().out
    assert '"benchmark": "self-improvement"' in out
    assert '"green": true' in out.lower()

def test_layer5_cli_dispatch_learning(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_LEARNING_DB", str(tmp_path / "learning.db"))
    monkeypatch.setenv("AGENT_SKILLS_DB", str(tmp_path / "skills.db"))
    inputs = iter(["/learning calculate 2+2", "exit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    cli.main()
    out = capsys.readouterr().out
    assert out.strip().endswith("[]")


def test_cli_hides_runtime_state_until_debug_enabled(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    state = SimpleNamespace(
        run_id="private-run-id",
        plan=SimpleNamespace(steps=[], planner="test", estimated_cost=0.0, estimated_duration=0.0),
        status="completed",
        replans=0,
        final_message="أهلًا بيك 👋 أنا شوري.",
    )
    monkeypatch.setattr(cli, "run_agent", lambda *args, **kwargs: state)
    inputs = iter(["hello", "/debug", "hello", "exit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    cli.main()
    out = capsys.readouterr().out
    default_output, debug_output = out.split("Debug mode: on", 1)
    assert "أهلًا بيك 👋 أنا شوري." in default_output
    assert "private-run-id" not in default_output
    assert "private-run-id" in debug_output

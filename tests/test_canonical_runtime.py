from __future__ import annotations
from types import SimpleNamespace
import app.interfaces.cli as cli

def test_cli_uses_canonical_brain_runtime_for_natural_and_agent_commands(monkeypatch):
    calls=[]
    def fake_runtime(message, **kwargs):
        calls.append(message)
        return SimpleNamespace(status='completed', response='ok')
    monkeypatch.setattr(cli, 'run_brain', fake_runtime)
    monkeypatch.setattr(cli, 'run_agent', fake_runtime)
    inputs=iter(['hello','/agent calculate 2+2','exit'])
    monkeypatch.setattr('builtins.input', lambda *_: next(inputs))
    cli.main()
    assert calls == ['hello','calculate 2+2']

def test_cli_canonical_alias_is_brain_runtime():
    assert cli.run_agent is cli.run_brain

from __future__ import annotations

import app.interfaces.cli as cli


class _Proposal:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def to_dict(self):
        return self.payload


class _FakeCompanyManager:
    calls = []

    def propose_skill_promotion(self, key, *, producer):
        self.calls.append(("promotion", key, producer))
        return _Proposal({"kind": "promotion", "producer": producer})

    def propose_skill_acquisition(self, **kwargs):
        self.calls.append(("acquisition", kwargs))
        return _Proposal({"kind": "acquisition", **kwargs})

    def grant_skill_trust(self, proposal_id, *, reviewer, trust_level, reason):
        self.calls.append(("trust", proposal_id, reviewer, trust_level, reason))
        return _Proposal({"kind": "trust", "reviewer": reviewer, "trust_level": trust_level, "reason": reason})

    def rollback_skill(self, key, *, actor, reason):
        self.calls.append(("rollback", key, actor, reason))
        return {"kind": "rollback", "actor": actor, "reason": reason}


def _run(monkeypatch, capsys, tmp_path, command):
    monkeypatch.chdir(tmp_path)
    _FakeCompanyManager.calls = []
    monkeypatch.setattr("app.organization.CompanySelfImprovementManager", _FakeCompanyManager)
    inputs = iter([command, "exit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    cli.main()
    return capsys.readouterr().out


def test_c15_cli_promotion_passes_mandatory_producer(monkeypatch, capsys, tmp_path):
    out = _run(monkeypatch, capsys, tmp_path, "/company-improve-skill candidate:test|data:data-analyst")
    assert '"producer": "data:data-analyst"' in out
    assert _FakeCompanyManager.calls == [("promotion", "candidate:test", "data:data-analyst")]


def test_c15_cli_acquisition_passes_mandatory_producer(monkeypatch, capsys, tmp_path):
    out = _run(
        monkeypatch, capsys, tmp_path,
        '/company-acquire-skill c17:test|Test skill|runtime|data:data-analyst|[{"tool":"calculator"}]',
    )
    assert '"producer": "data:data-analyst"' in out
    kind, kwargs = _FakeCompanyManager.calls[0]
    assert kind == "acquisition"
    assert kwargs["producer"] == "data:data-analyst"
    assert kwargs["workflow"] == [{"tool": "calculator"}]


def test_c15_cli_exposes_governed_trust_grant(monkeypatch, capsys, tmp_path):
    out = _run(
        monkeypatch, capsys, tmp_path,
        "/company-skill-trust chg:test|security:reviewer|trusted|independent verification",
    )
    assert '"trust_level": "trusted"' in out
    assert _FakeCompanyManager.calls == [
        ("trust", "chg:test", "security:reviewer", "trusted", "independent verification")
    ]


def test_c15_cli_rollback_passes_actor_and_reason(monkeypatch, capsys, tmp_path):
    out = _run(monkeypatch, capsys, tmp_path, "/company-skill-rollback active:test|security:reviewer|verified regression")
    assert '"actor": "security:reviewer"' in out
    assert _FakeCompanyManager.calls == [
        ("rollback", "active:test", "security:reviewer", "verified regression")
    ]

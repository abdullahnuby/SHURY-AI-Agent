from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.learning.store import LearningStore
from app.organization.capability_planning import CapabilityCandidate
from app.organization.routing import AdaptiveDelegationController


class _Org:
    def __init__(self):
        self.roles = {
            "data:loaded": SimpleNamespace(key="data:loaded", department="data", agent_class="builder"),
            "data:free": SimpleNamespace(key="data:free", department="data", agent_class="builder"),
            "security:reviewer": SimpleNamespace(key="security:reviewer", department="security", agent_class="reviewer"),
        }

    def resolve_owner(self, **kwargs):
        return SimpleNamespace(department="data")

    def role(self, key):
        return self.roles[key]


def _candidate(role: str, *, fit: float = 1.0, tool: str = "tool-a") -> CapabilityCandidate:
    return CapabilityCandidate(
        requirement_key="r1", tool=tool, skill_key="skill-a", capability="analysis",
        department="data", specialist=role, fit=fit, cost=1.0, risk="low",
        verification_level="standard", reason="qualified",
    )


def _seed_evidence(store: LearningStore, role: str):
    for i in range(10):
        store.record_company_delegation_outcome(
            capability="analysis", department="data", specialist=role, skill_key="skill-a",
            tool="tool-a", verified=True, run_id=f"{role}-ok-{i}"
        )


def _seed_load(store: LearningStore, role: str, count: int):
    store.create_company_project({"project_id": "p1", "name": "P1", "objective": "load"})
    for i in range(count):
        store.upsert_company_project_task({
            "project_id": "p1", "task_id": f"task-{role}-{i}", "objective": "active",
            "department": "data", "specialist": role, "status": "pending", "ready": True,
        })


def test_c18_controller_requires_canonical_learning_store(tmp_path: Path):
    with pytest.raises(TypeError):
        AdaptiveDelegationController(_Org(), None)


def test_c18_equal_fit_prefers_less_loaded_specialist_from_canonical_portfolio(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    _seed_evidence(store, "data:loaded")
    _seed_evidence(store, "data:free")
    _seed_load(store, "data:loaded", 4)
    controller = AdaptiveDelegationController(_Org(), store)
    ranked = controller.rank((_candidate("data:loaded"), _candidate("data:free")))
    assert [row.candidate.specialist for row in ranked] == ["data:free", "data:loaded"]
    assert ranked[0].workload_score < ranked[1].workload_score


def test_c18_rejects_candidate_when_structured_owner_does_not_match_candidate_department(tmp_path: Path):
    class WrongOwner(_Org):
        def resolve_owner(self, **kwargs):
            return SimpleNamespace(department="finance")

    store = LearningStore(tmp_path / "learning.db")
    _seed_evidence(store, "data:free")
    controller = AdaptiveDelegationController(WrongOwner(), store)
    assert controller.rank((_candidate("data:free"),)) == ()


def test_c18_routing_does_not_make_reviewer_or_unknown_role_eligible(tmp_path: Path):
    store = LearningStore(tmp_path / "learning.db")
    controller = AdaptiveDelegationController(_Org(), store)
    unknown = _candidate("data:missing")
    reviewer = _candidate("security:reviewer")
    assert controller.rank((unknown, reviewer)) == ()


def test_c18_cli_exposes_routing_without_execution_authority(monkeypatch, capsys, tmp_path: Path):
    import app.interfaces.cli as cli
    monkeypatch.chdir(tmp_path)
    inputs = iter(["/company-routing data_analysis", "exit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    store_path = tmp_path / "learning.db"
    store = LearningStore(store_path)
    for i in range(4):
        store.record_company_delegation_outcome(
            capability="data_analysis", department="data", specialist="data:data-analyst",
            skill_key="", tool="analyze_dataset", verified=True, run_id=f"cli-ok-{i}"
        )
    monkeypatch.setenv("AGENT_LEARNING_DB", str(store_path))
    cli.main()
    out = capsys.readouterr().out
    assert '"capability": "data_analysis"' in out
    assert '"routing_score"' in out
    assert '"active_tasks"' in out

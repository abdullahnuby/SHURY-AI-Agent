from pathlib import Path
import json
import pytest

from app.organization import CompanySelfImprovementManager
from app.learning.store import LearningStore
from app.skills.registry import SkillBank


def _manager(tmp_path):
    learning = LearningStore(tmp_path / "learning.db")
    skills = SkillBank(tmp_path / "skills.db", bootstrap=False)
    return CompanySelfImprovementManager(learning_store=learning, skill_bank=skills), learning, skills


def test_skill_acquisition_starts_as_quarantined_candidate(tmp_path):
    mgr, _, skills = _manager(tmp_path)
    proposal = mgr.propose_skill_acquisition(
        key="acquired:local",
        name="Local acquired skill",
        producer="data:data-analyst",
        triggers=("analyze",),
        workflow=({"tool": "calculator", "capability": "calculate"},),
        source="self-improvement",
        evidence=[{"kind": "verified-procedure", "run_id": "r1", "verified": True}],
        verification=({"tool": "calculator", "args": {"expression": "2 + 2"}, "expect": 4},),
    )
    assert proposal.status == "proposed"
    assert skills.get("acquired:local").status == "candidate"
    assert skills.trust("acquired:local") == "quarantined"


def test_promotion_is_proposal_only_until_governed_apply(tmp_path, monkeypatch):
    mgr, _, skills = _manager(tmp_path)
    skills.upsert(key="candidate:promote", name="Promote me", triggers=("calculate",), workflow=({"tool": "calculator", "capability": "calculate"},), status="candidate")
    class FakeLM:
        def evaluate_candidate(self, *args, **kwargs):
            return {"gate": {"promotable": True}, "evaluations": []}
    mgr.learning_manager = FakeLM()
    proposal = mgr.propose_skill_promotion("candidate:promote", producer="data:data-analyst")
    assert proposal.status == "proposed"
    assert skills.get("candidate:promote").status == "candidate"


def test_regression_gate_blocks_skill_promotion_without_change_specific_evidence(tmp_path, monkeypatch):
    mgr, _, skills = _manager(tmp_path)
    skills.upsert(key="candidate:blocked", name="Blocked", triggers=("calculate",), workflow=({"tool": "calculator", "capability": "calculate"},), status="candidate")
    proposal_row = mgr.learning.create_company_change_proposal(
        proposal_id="chg:test-blocked", company_id="shury-company", change_kind="skill_promotion", target_key="candidate:blocked",
        payload={}, evidence=[{"kind": "run", "run_id": "r1", "verified": True}],
        regression={"status": "not_run", "promotion_gate": {"promotable": False}},
    )
    monkeypatch.setattr("app.evaluation.company.CompanyEvaluationSuite.evaluate", lambda self: type("R", (), {"to_dict": lambda self: {"pass_rate": 1.0, "pass_count": 11, "case_count": 11, "safety_violations": 0, "ambiguous_ownership_failures": 0, "reviewer_independence_failures": 0, "recovery_failures": 0, "context_isolation_failures": 0, "unnecessary_delegation_rate": 0.0}})())
    monkeypatch.setattr("app.evaluation.self_improvement_benchmark.run_self_improvement_benchmark", lambda: {"green": True, "passed": 7, "total": 7})
    out = mgr.run_regression_gate(proposal_row["proposal_id"])
    assert out["status"] == "failed"
    assert mgr.get(proposal_row["proposal_id"]).status == "blocked"


def test_security_review_requires_reviewer_class(tmp_path):
    mgr, learning, skills = _manager(tmp_path)
    proposal = mgr.propose_skill_acquisition(
        key="acquired:review", name="Review me", producer="data:data-analyst", triggers=("calculate",), workflow=({"tool": "calculator", "capability": "calculate"},),
        source="self-improvement", evidence=[{"kind": "verified", "run_id": "r1", "verified": True}], verification=({"tool": "calculator", "args": {"expression": "2 + 2"}, "expect": 4},),
    )
    with pytest.raises(PermissionError):
        mgr.security_review(proposal.proposal_id, reviewer="data:data-analyst", approved=True)


def test_ceo_approval_requires_security_and_regression(tmp_path, monkeypatch):
    mgr, learning, skills = _manager(tmp_path)
    proposal = mgr.propose_skill_acquisition(
        key="acquired:approve", name="Approve me", producer="data:data-analyst", triggers=("calculate",), workflow=({"tool": "calculator", "capability": "calculate"},),
        source="self-improvement", evidence=[{"kind": "verified", "run_id": "r1", "verified": True}], verification=({"tool": "calculator", "args": {"expression": "2 + 2"}, "expect": 4},),
    )
    with pytest.raises(PermissionError):
        mgr.approve(proposal.proposal_id)
    monkeypatch.setattr("app.evaluation.company.CompanyEvaluationSuite.evaluate", lambda self: type("R", (), {"to_dict": lambda self: {"pass_rate": 1.0, "pass_count": 11, "case_count": 11, "safety_violations": 0, "ambiguous_ownership_failures": 0, "reviewer_independence_failures": 0, "recovery_failures": 0, "context_isolation_failures": 0, "unnecessary_delegation_rate": 0.0}})())
    monkeypatch.setattr("app.evaluation.self_improvement_benchmark.run_self_improvement_benchmark", lambda: {"green": True, "passed": 7, "total": 7})
    # acquisition can pass change-specific evidence without promotion evidence
    mgr.run_regression_gate(proposal.proposal_id)
    proposal = mgr.security_review(proposal.proposal_id, reviewer="security:reviewer", approved=True, reason="bounded and reversible")
    mgr.grant_skill_trust(proposal.proposal_id, reviewer="security:reviewer", trust_level="trusted", reason="independent verification passed")
    proposal = mgr.approve(proposal.proposal_id)
    assert proposal.status == "approved"
    proposal = mgr.apply(proposal.proposal_id)
    assert proposal.status == "monitoring"
    assert skills.get("acquired:approve").status == "active"


def test_topology_changes_are_staged_not_applied(tmp_path):
    mgr, _, _ = _manager(tmp_path)
    proposal = mgr.propose_organization_change(
        change_kind="role_change", target_key="data:data-analyst",
        payload={"add_capability": "forecasting", "reason": "repeated verified demand"},
        producer="data:data-analyst", evidence=[{"kind": "trend", "runs": ["r1", "r2", "r3"], "verified": True}],
    )
    assert proposal.status == "proposed"
    assert proposal.payload["add_capability"] == "forecasting"
    with pytest.raises(PermissionError):
        mgr.apply(proposal.proposal_id)


def test_skill_rollback_preserves_evidence(tmp_path):
    mgr, learning, skills = _manager(tmp_path)
    skills.upsert(key="active:rollback", name="Rollback me", triggers=("calculate",), workflow=({"tool": "calculator", "capability": "calculate"},), status="active")
    result = mgr.rollback_skill("active:rollback", actor="security:reviewer", reason="verified regression")
    assert result["status"] == "applied"
    assert result["before"]["status"] == "active"
    assert result["after"]["status"] == "candidate"
    assert result["proposal_id"]
    assert skills.get("active:rollback").status == "candidate"
    # The rollback evidence lives in the canonical LearningStore event ledger.
    import sqlite3
    conn = sqlite3.connect(learning.path)
    try:
        rows = conn.execute("SELECT action FROM evolution_events WHERE action='company_skill_rollback'").fetchall()
    finally:
        conn.close()
    assert rows


def test_proposals_persist_in_canonical_learning_store(tmp_path):
    mgr, learning, _ = _manager(tmp_path)
    proposal = mgr.propose_organization_change(
        change_kind="capability_change", target_key="data_analysis",
        payload={"owner": "data", "reason": "verified workload concentration"},
        producer="data:data-analyst", evidence=[{"kind": "experience", "run_id": "r99", "verified": True}],
    )
    fresh = CompanySelfImprovementManager(learning_store=learning, skill_bank=SkillBank(tmp_path / "skills.db", bootstrap=False))
    found = fresh.get(proposal.proposal_id)
    assert found is not None
    assert found.status == "proposed"

def test_real_promotion_proposal_uses_company_skillbank(tmp_path):
    mgr, _, skills = _manager(tmp_path)
    skills.upsert(key="candidate:real", name="Real candidate", triggers=("calculate",), workflow=({"tool": "calculator", "capability": "calculate"},), status="candidate")
    proposal = mgr.propose_skill_promotion("candidate:real", producer="data:data-analyst")
    assert proposal.target_key == "candidate:real"
    assert proposal.status == "proposed"
    assert "promotion_gate" in proposal.regression
    assert skills.get("candidate:real").status == "candidate"


def test_deprecation_requires_negative_lifecycle_evidence(tmp_path, monkeypatch):
    mgr, _, skills = _manager(tmp_path)
    skills.upsert(key="active:deprecated", name="Deprecate candidate", triggers=("calculate",), workflow=({"tool": "calculator", "capability": "calculate"},), status="active")
    monkeypatch.setattr(skills, "adaptive_evidence", lambda key: {"recommendation": "observe", "mean_delta": 0.0, "count": 4})
    proposal = mgr.propose_skill_deprecation("active:deprecated", producer="data:data-analyst")
    monkeypatch.setattr("app.evaluation.company.CompanyEvaluationSuite.evaluate", lambda self: type("R", (), {"to_dict": lambda self: {"pass_rate": 1.0, "pass_count": 11, "case_count": 11, "safety_violations": 0, "ambiguous_ownership_failures": 0, "reviewer_independence_failures": 0, "recovery_failures": 0, "context_isolation_failures": 0, "unnecessary_delegation_rate": 0.0}})())
    monkeypatch.setattr("app.evaluation.self_improvement_benchmark.run_self_improvement_benchmark", lambda: {"green": True, "passed": 9, "total": 9})
    out = mgr.run_regression_gate(proposal.proposal_id)
    assert out["status"] == "failed"
    assert mgr.get(proposal.proposal_id).status == "blocked"

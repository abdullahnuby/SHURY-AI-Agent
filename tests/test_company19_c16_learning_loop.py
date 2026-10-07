import pytest

from app.organization import CompanySelfImprovementManager
from app.learning.store import LearningStore
from app.skills.registry import SkillBank


def _manager(tmp_path, monkeypatch):
    learning = LearningStore(tmp_path / "learning.db")
    skills = SkillBank(tmp_path / "skills.db", bootstrap=False)
    mgr = CompanySelfImprovementManager(learning_store=learning, skill_bank=skills)

    class FakeLM:
        def evaluate_candidate(self, *args, **kwargs):
            return {"gate": {"promotable": True}, "evaluations": []}

    mgr.learning_manager = FakeLM()
    report = {
        "pass_rate": 1.0,
        "pass_count": 11,
        "case_count": 11,
        "safety_violations": 0,
        "ambiguous_ownership_failures": 0,
        "reviewer_independence_failures": 0,
        "recovery_failures": 0,
        "context_isolation_failures": 0,
        "unnecessary_delegation_rate": 0.0,
    }
    monkeypatch.setattr(mgr, "_isolated_company_eval", lambda **kwargs: dict(report))
    monkeypatch.setattr(
        "app.evaluation.self_improvement_benchmark.run_self_improvement_benchmark",
        lambda: {"green": True, "passed": 9, "total": 9},
    )
    skills.upsert(
        key="active:c16",
        name="C16 learning skill",
        triggers=("read",),
        workflow=({"tool": "read_file", "capability": "file_read"},),
        verification=({"tool": "read_file", "args": {"path": "workspace/missing-c16-file"}},),
        status="candidate",
    )
    skills.set_trust("active:c16", "local")
    proposal = mgr.propose_skill_promotion("active:c16", producer="operations:file-specialist")
    mgr.run_regression_gate(proposal.proposal_id)
    mgr.security_review(proposal.proposal_id, reviewer="security:reviewer", approved=True, reason="independent review")
    mgr.approve(proposal.proposal_id)
    applied = mgr.apply(proposal.proposal_id)
    assert applied.status == "monitoring"
    return mgr, learning, skills, applied


def test_c16_verified_outcome_feeds_memory_and_specialist_reliability(tmp_path, monkeypatch):
    mgr, learning, _, proposal = _manager(tmp_path, monkeypatch)
    result = mgr.record_post_change_outcome(
        proposal.proposal_id,
        capability="file_read",
        department="operations",
        specialist="operations:file-specialist",
        tool="read_file",
        success=True,
        verified=True,
        run_id="c16-run-1",
        task_signature="unseen-signature-1",
        evidence=["company-run:c16-run-1"],
    )
    assert result["unseen"] is True
    assert result["company_memory_id"] is not None
    rows = learning.company_delegation_evidence(capability="file_read")
    row = next(x for x in rows if x["specialist"] == "operations:file-specialist")
    assert row["attempts"] == 1
    assert row["verified_successes"] == 1
    memory_stats = mgr.company_id and __import__("app.organization.company_memory", fromlist=["CompanyMemory"]).CompanyMemory(company_id=mgr.company_id).stats()
    assert memory_stats["categories"].get("outcome", 0) >= 1


def test_c16_rejects_verification_task_as_unseen_outcome(tmp_path, monkeypatch):
    mgr, _, _, proposal = _manager(tmp_path, monkeypatch)
    sig = proposal.regression["change_specific"]["verification_signatures"][0]
    with pytest.raises(PermissionError):
        mgr.record_post_change_outcome(
            proposal.proposal_id,
            capability="file_read",
            department="operations",
            specialist="operations:file-specialist",
            tool="read_file",
            success=True,
            verified=True,
            run_id="c16-run-seen",
            task_signature=sig,
            evidence=["company-run:c16-run-seen"],
        )


def test_c16_keep_requires_generalization_and_reports_org_level_separately(tmp_path, monkeypatch):
    mgr, _, _, proposal = _manager(tmp_path, monkeypatch)
    mgr.record_post_change_outcome(
        proposal.proposal_id,
        capability="file_read",
        department="operations",
        specialist="operations:file-specialist",
        tool="read_file",
        success=True,
        verified=True,
        run_id="c16-run-keep",
        task_signature="unseen-success",
        evidence=["company-run:c16-run-keep"],
    )
    verdict = mgr.monitor_change(proposal.proposal_id)
    assert verdict["status"] == "keep"
    assert verdict["generalization"]["improved"] is True
    assert verdict["organization"]["non_regression"] is True
    assert "single_change" in verdict
    assert mgr.get(proposal.proposal_id).status == "monitoring"


def test_c16_regression_opens_rollback_proposal_without_auto_apply(tmp_path, monkeypatch):
    mgr, _, skills, proposal = _manager(tmp_path, monkeypatch)
    mgr.record_post_change_outcome(
        proposal.proposal_id,
        capability="file_read",
        department="operations",
        specialist="operations:file-specialist",
        tool="read_file",
        success=False,
        verified=True,
        run_id="c16-run-fail",
        task_signature="unseen-failure",
        failure_class="verified-regression",
        evidence=["company-run:c16-run-fail"],
    )
    verdict = mgr.monitor_change(proposal.proposal_id)
    assert verdict["status"] == "recommend_rollback"
    rollback_id = verdict["rollback_proposal_id"]
    assert rollback_id
    rollback = mgr.get(rollback_id)
    assert rollback is not None
    assert rollback.status == "proposed"
    assert rollback.change_kind == "skill_rollback"
    assert rollback.payload["source_proposal_id"] == proposal.proposal_id
    assert skills.get("active:c16").status == "active"


def test_c16_does_not_auto_open_duplicate_rollback_proposals(tmp_path, monkeypatch):
    mgr, _, _, proposal = _manager(tmp_path, monkeypatch)
    mgr.record_post_change_outcome(
        proposal.proposal_id,
        capability="file_read",
        department="operations",
        specialist="operations:file-specialist",
        tool="read_file",
        success=False,
        verified=True,
        run_id="c16-run-fail-1",
        task_signature="unseen-failure-1",
        evidence=["company-run:c16-run-fail-1"],
    )
    first = mgr.monitor_change(proposal.proposal_id)
    second = mgr.monitor_change(proposal.proposal_id)
    assert first["rollback_proposal_id"] == second["rollback_proposal_id"]
    rollbacks = [p for p in mgr.list(limit=1000) if p.change_kind == "skill_rollback" and p.payload.get("source_proposal_id") == proposal.proposal_id]
    assert len(rollbacks) == 1

import sqlite3
from types import SimpleNamespace

import pytest

from app.organization import CompanySelfImprovementManager, DEFAULT_COMPANY
from app.learning.store import LearningStore
from app.skills.registry import SkillBank
from app.organization.review import review_company_execution


def manager(tmp_path):
    return CompanySelfImprovementManager(
        learning_store=LearningStore(tmp_path / "learning.db"),
        skill_bank=SkillBank(tmp_path / "skills.db", bootstrap=False),
    )


def acquired(mgr, key="c18:skill", *, verification=({"tool": "calculator", "args": {"expression": "2 + 2"}, "expect": 4},)):
    return mgr.propose_skill_acquisition(
        key=key, name="C18 skill", producer="data:data-analyst",
        triggers=("calculate",), workflow=({"tool": "calculator", "capability": "calculate"},),
        verification=verification, evidence=[{"kind": "verified", "run_id": "r1"}],
    )


def pass_company(_self):
    return {"pass_rate": 1.0, "pass_count": 11, "case_count": 11, "safety_violations": 0,
            "ambiguous_ownership_failures": 0, "reviewer_independence_failures": 0,
            "recovery_failures": 0, "context_isolation_failures": 0, "unnecessary_delegation_rate": 0.0}


def test_acquisition_cannot_self_grant_trust(tmp_path):
    mgr = manager(tmp_path)
    with pytest.raises(TypeError):
        mgr.propose_skill_acquisition(key="c18:selftrust", name="x", producer="data:data-analyst", trust_level="trusted")
    proposal = acquired(mgr, "c18:quarantine")
    assert mgr.skills.trust(proposal.target_key) == "quarantined"


def test_trust_grant_requires_independent_reviewer_reason_and_event(tmp_path):
    mgr = manager(tmp_path)
    proposal = acquired(mgr)
    with pytest.raises(PermissionError):
        mgr.grant_skill_trust(proposal.proposal_id, reviewer="data:data-analyst", trust_level="trusted", reason="x")
    with pytest.raises(PermissionError):
        mgr.grant_skill_trust(proposal.proposal_id, reviewer="security:reviewer", trust_level="trusted", reason="")
    mgr.grant_skill_trust(proposal.proposal_id, reviewer="security:reviewer", trust_level="trusted", reason="verified provenance")
    events = mgr.learning.recent_evolution_events(candidate_key=proposal.proposal_id)
    assert any(e["action"] == "company_skill_trust_granted" for e in events)


def test_missing_producer_is_fail_closed_and_self_review_is_logged(tmp_path):
    mgr = manager(tmp_path)
    with pytest.raises(TypeError):
        mgr.propose_skill_promotion("missing")
    with pytest.raises(PermissionError):
        mgr.propose_skill_acquisition(key="c18:badproducer", name="x", producer="not:a:role")
    proposal = acquired(mgr, "c18:selfreview")
    with pytest.raises(PermissionError):
        mgr.security_review(proposal.proposal_id, reviewer="data:data-analyst", approved=True, reason="self")
    events = mgr.learning.recent_evolution_events(candidate_key=proposal.proposal_id)
    assert any(e["action"] == "company_change_review_rejected" for e in events)


def test_rollback_requires_authority_and_creates_applied_change_record(tmp_path):
    mgr = manager(tmp_path)
    mgr.skills.upsert(key="c18:rollback", name="rollback", triggers=("x",), workflow=(), status="active")
    with pytest.raises(PermissionError):
        mgr.rollback_skill("c18:rollback", actor="data:data-analyst", reason="no")
    with pytest.raises(PermissionError):
        mgr.rollback_skill("c18:rollback", actor="security:reviewer", reason="")
    result = mgr.rollback_skill("c18:rollback", actor="security:reviewer", reason="monitor regression")
    row = mgr.get(result["proposal_id"])
    assert row and row.change_kind == "skill_rollback" and row.status == "applied"
    assert row.payload["before"]["status"] == "active"
    assert row.payload["after"]["status"] == "candidate"


def test_apply_rejects_tampered_payload_after_approval(tmp_path, monkeypatch):
    mgr = manager(tmp_path)
    proposal = acquired(mgr, "c18:fingerprint")
    mgr.run_regression_gate = lambda _pid: {"status": "passed"}
    mgr.learning.update_company_change_proposal(proposal.proposal_id, status="evaluated", regression={"status": "passed"})
    proposal = mgr.security_review(proposal.proposal_id, reviewer="security:reviewer", approved=True, reason="reviewed")
    mgr.grant_skill_trust(proposal.proposal_id, reviewer="security:reviewer", trust_level="trusted", reason="trusted independently")
    proposal = mgr.approve(proposal.proposal_id)
    conn = sqlite3.connect(mgr.learning.path)
    with conn:
        conn.execute("UPDATE company_change_proposals SET payload=? WHERE proposal_id=?", ('{"producer":"data:data-analyst","skill":{}}', proposal.proposal_id))
    with pytest.raises(PermissionError, match="fingerprint"):
        mgr.apply(proposal.proposal_id)


def test_apply_requires_governed_trust_even_if_skill_field_was_tampered(tmp_path):
    mgr = manager(tmp_path)
    proposal = acquired(mgr, "c18:trust-tamper")
    mgr.learning.update_company_change_proposal(proposal.proposal_id, status="evaluated", regression={"status": "passed"})
    mgr.skills.set_trust(proposal.target_key, "trusted")
    mgr.security_review(proposal.proposal_id, reviewer="security:reviewer", approved=True, reason="reviewed")
    mgr.approve(proposal.proposal_id)
    with pytest.raises(PermissionError, match="trusted through independent governance"):
        mgr.apply(proposal.proposal_id)


def test_regression_requires_executable_verification_cases(tmp_path, monkeypatch):
    mgr = manager(tmp_path)
    proposal = acquired(mgr, "c18:no-cases", verification=())
    monkeypatch.setattr(mgr, "_isolated_company_eval", lambda **_: pass_company(None))
    monkeypatch.setattr("app.evaluation.self_improvement_benchmark.run_self_improvement_benchmark", lambda: {"green": True})
    out = mgr.run_regression_gate(proposal.proposal_id)
    assert out["status"] == "failed"
    assert out["change_specific"]["case_count"] == 0


def test_regression_records_change_specific_and_company_before_after(tmp_path, monkeypatch):
    mgr = manager(tmp_path)
    proposal = acquired(mgr, "c18:regression")
    monkeypatch.setattr(mgr, "_isolated_company_eval", lambda **kwargs: pass_company(None))
    monkeypatch.setattr("app.evaluation.self_improvement_benchmark.run_self_improvement_benchmark", lambda: {"green": True})
    out = mgr.run_regression_gate(proposal.proposal_id)
    assert out["status"] == "passed"
    assert out["change_specific"]["passed"] is True
    assert "company_evaluation_before" in out and "company_evaluation_after" in out
    assert out["change_specific"]["company_non_regression"] is True


def test_apply_enters_monitoring_and_monitor_never_rolls_back(tmp_path, monkeypatch):
    mgr = manager(tmp_path)
    proposal = acquired(mgr, "c18:monitor")
    monkeypatch.setattr(mgr, "_isolated_company_eval", lambda **kwargs: pass_company(None))
    monkeypatch.setattr("app.evaluation.self_improvement_benchmark.run_self_improvement_benchmark", lambda: {"green": True})
    mgr.run_regression_gate(proposal.proposal_id)
    mgr.security_review(proposal.proposal_id, reviewer="security:reviewer", approved=True, reason="bounded")
    mgr.grant_skill_trust(proposal.proposal_id, reviewer="security:reviewer", trust_level="trusted", reason="verified")
    mgr.approve(proposal.proposal_id)
    applied = mgr.apply(proposal.proposal_id)
    assert applied.status == "monitoring"
    assert "baseline_at_apply" in applied.regression
    assert applied.regression["baseline_at_apply"]["skill"]["status"] == "candidate"
    verdict = mgr.monitor_change(proposal.proposal_id)
    # C16 deliberately fails closed when no verified unseen-task evidence exists.
    # Monitoring may recommend rollback, but it must never mutate the Skill automatically.
    assert verdict["status"] == "recommend_rollback"
    assert verdict["rollback_proposal_id"]
    assert mgr.skills.get("c18:monitor").status == "active"
    assert mgr.get(proposal.proposal_id).status == "monitoring"


def test_review_uses_assignments_not_operation_name():
    plan = SimpleNamespace(steps=[
        SimpleNamespace(id="s1", tool="list_files_recursive", status="done", output={"ok": True}),
        SimpleNamespace(id="s2", tool="analyze_csv_by_average", status="done", output={
            "verified": True, "selection_metric": "average", "selected_path": "sales.csv",
            "selected": {"average": 20, "source_fingerprint": "h"},
            "files": [{"path": "sales.csv", "average": 20}],
        }),
        SimpleNamespace(id="s3", tool="create_sales_analysis_report", status="done", output={"verified": True, "report_reread_verified": True}),
        SimpleNamespace(id="s4", tool="move_workspace_report", status="done", output={"verified": True, "fingerprint_match": True, "destination_exists": True, "source_removed": True, "destination": "out/report.md", "sha256_before": "h", "sha256_after": "h"}),
        SimpleNamespace(id="s5", tool="read_file", status="done", output={"path": "out/report.md", "content": "sales.csv out/report.md h"}),
    ])
    assignments = [
        {"department": "operations", "tool": "list_files_recursive", "reviewers": ["qa:reviewer"]},
        {"department": "data", "tool": "analyze_csv_by_average", "reviewers": ["qa:reviewer"]},
        {"department": "data", "tool": "create_sales_analysis_report", "reviewers": ["qa:reviewer"]},
        {"department": "operations", "tool": "move_workspace_report", "reviewers": ["security:reviewer", "qa:reviewer"]},
        {"department": "operations", "tool": "read_file", "reviewers": ["qa:reviewer"]},
    ]
    review = review_company_execution(goal="novel", operation="brand_new_operation_name", plan=plan, assignments=assignments, status="completed")
    assert review.ok, review.to_dict()


def test_review_rejects_new_operation_without_required_security_assignment():
    plan = SimpleNamespace(steps=[
        SimpleNamespace(id="s1", tool="list_files_recursive", status="done", output={"ok": True}),
        SimpleNamespace(id="s2", tool="analyze_csv_by_average", status="done", output={
            "verified": True, "selection_metric": "average", "selected_path": "sales.csv",
            "selected": {"average": 20, "source_fingerprint": "h"},
            "files": [{"path": "sales.csv", "average": 20}],
        }),
        SimpleNamespace(id="s3", tool="create_sales_analysis_report", status="done", output={"verified": True, "report_reread_verified": True}),
        SimpleNamespace(id="s4", tool="move_workspace_report", status="done", output={"verified": True, "fingerprint_match": True, "destination_exists": True, "source_removed": True, "destination": "out/report.md", "sha256_before": "h", "sha256_after": "h"}),
        SimpleNamespace(id="s5", tool="read_file", status="done", output={"path": "out/report.md", "content": "sales.csv out/report.md h"}),
    ])
    assignments = [
        {"department": "operations", "tool": "list_files_recursive", "reviewers": ["qa:reviewer"]},
        {"department": "data", "tool": "analyze_csv_by_average", "reviewers": ["qa:reviewer"]},
        {"department": "data", "tool": "create_sales_analysis_report", "reviewers": ["qa:reviewer"]},
        {"department": "operations", "tool": "move_workspace_report", "reviewers": ["qa:reviewer"]},
        {"department": "operations", "tool": "read_file", "reviewers": ["qa:reviewer"]},
    ]
    review = review_company_execution(goal="novel", operation="brand_new_operation_name", plan=plan, assignments=assignments, status="completed")
    assert review.ok is False
    assert "report_move_has_security_review" in review.reason


def test_acquisition_regression_gate_rejects_without_verification_cases_directly(tmp_path, monkeypatch):
    mgr = manager(tmp_path)
    mgr.skills.upsert(key="c18:gate-direct", name="candidate", triggers=("calculate",), workflow=({"tool": "calculator", "capability": "calculate"},), status="candidate")
    row = mgr.learning.create_company_change_proposal(
        proposal_id="chg:c18-gate-direct", company_id="shury-company", change_kind="skill_acquisition",
        target_key="c18:gate-direct", payload={"producer": "data:data-analyst", "skill": {"key": "c18:gate-direct"}},
        evidence=[{"verified": True}], regression={"status": "not_run"},
    )
    monkeypatch.setattr(mgr, "_isolated_company_eval", lambda **_: pass_company(None))
    monkeypatch.setattr("app.evaluation.self_improvement_benchmark.run_self_improvement_benchmark", lambda: {"green": True})
    out = mgr.run_regression_gate(row["proposal_id"])
    assert out["status"] == "failed"
    assert out["change_specific"]["case_count"] == 0


def test_apply_fingerprint_rejects_tampered_promotion_payload_directly(tmp_path):
    mgr = manager(tmp_path)
    mgr.skills.upsert(key="c18:fingerprint-direct", name="candidate", triggers=("calculate",), workflow=(), status="candidate")
    payload = {"before_status": "candidate", "before_version": 1, "producer": "data:data-analyst"}
    row = mgr.learning.create_company_change_proposal(
        proposal_id="chg:c18-fp-direct", company_id="shury-company", change_kind="skill_promotion",
        target_key="c18:fingerprint-direct", payload=payload, evidence=[], regression={"status": "passed"},
    )
    from app.organization.self_improvement import _fingerprint
    fp = _fingerprint({"proposal_id": row["proposal_id"], "kind": row["change_kind"], "target": row["target_key"], "payload": payload})
    mgr.learning.update_company_change_proposal(row["proposal_id"], status="approved", regression={"status": "passed"}, executive_approval={"approver": DEFAULT_COMPANY.ceo.key, "approved": True, "fingerprint": fp})
    conn = sqlite3.connect(mgr.learning.path)
    with conn:
        conn.execute("UPDATE company_change_proposals SET payload=? WHERE proposal_id=?", ('{"before_status":"candidate","before_version":999,"producer":"data:data-analyst"}', row["proposal_id"]))
    with pytest.raises(PermissionError, match="fingerprint"):
        mgr.apply(row["proposal_id"])


def test_approve_rejects_when_ceo_is_also_producer(tmp_path):
    mgr = manager(tmp_path)
    proposal = mgr.propose_organization_change(
        change_kind="capability_change", target_key="data_analysis",
        payload={"reason": "collision"}, producer=DEFAULT_COMPANY.ceo.key, evidence=[{"verified": True}],
    )
    mgr.learning.update_company_change_proposal(proposal.proposal_id, status="evaluated", regression={"status": "passed"}, security_review={"approved": True, "reviewer": "security:reviewer", "reason": "reviewed"})
    with pytest.raises(PermissionError):
        mgr.approve(proposal.proposal_id, approver=DEFAULT_COMPANY.ceo.key)
    events = mgr.learning.recent_evolution_events(candidate_key=proposal.proposal_id)
    assert any(e["action"] == "company_change_approval_rejected" for e in events)

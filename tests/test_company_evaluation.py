from app.evaluation import CompanyEvaluationSuite, company_release_gate


def test_company_evaluation_suite_covers_required_categories():
    report = CompanyEvaluationSuite().evaluate()
    categories = {r.case_id for r in report.results}
    assert {
        "single_department", "two_departments", "three_departments", "novel_goal",
        "wrong_owner", "ambiguous_ownership", "reviewer_independence",
        "failure_redelegation", "context_saturation", "unnecessary_delegation", "canonical_brain_delegation",
    } <= categories


def test_company_evaluation_is_ready():
    report = CompanyEvaluationSuite().evaluate()
    assert report.pass_rate == 1.0, report.to_dict()
    assert report.safety_violations == 0
    assert report.ambiguous_ownership_failures == 0
    assert report.reviewer_independence_failures == 0
    assert report.recovery_failures == 0
    assert report.context_isolation_failures == 0
    assert report.unnecessary_delegation_rate <= 0.05
    gate = company_release_gate(report)
    assert gate["company_ready"] is True, gate

from pathlib import Path


def test_company_suite_does_not_write_db_files_into_app_data():
    from app.evaluation.company import CompanyEvaluationSuite

    report = CompanyEvaluationSuite().evaluate().to_dict()
    assert report["case_count"] > 0
    assert not list(Path("app/data").glob("*.db"))

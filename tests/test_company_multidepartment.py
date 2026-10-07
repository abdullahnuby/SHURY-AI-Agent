from app.brain.models import CandidateAction, PlannedAction, SemanticFrame
from app.brain.methods import _cross_department_data_move
from app.organization import DEFAULT_COMPANY


def test_cross_department_method_builds_data_then_operations_workflow():
    frame = SemanticFrame(
        text="analyze csv files then move the largest and write a report",
        language="en", speech_act="command", concepts=(),
        requested_operation="cross_department_data_move",
    )
    tools = [
        ("list_files_recursive", "workspace_recursive_inventory"),
        ("analyze_csv_collection", "cross_department_data_move"),
        ("move_workspace_file", "cross_department_data_move"),
        ("create_company_data_report", "cross_department_data_move"),
        ("read_file", "file_read"),
    ]
    candidates = [CandidateAction(capability=c, tool=t, score=10, reason="test",
                                  requires_input=(), reversible=True, preconditions=(),
                                  effects=("effect",), risk="low", cost=1.0) for t, c in tools]
    plan = _cross_department_data_move(frame, candidates)
    assert [step.tool for step in plan] == [
        "list_files_recursive", "analyze_csv_collection", "move_workspace_file",
        "create_company_data_report", "read_file"
    ]
    assert plan[0].args.get('exclude_path') == 'company_data_report.md'
    assert plan[1].depends_on == ("s1",)
    assert plan[2].depends_on == ("s2",)
    assert plan[3].depends_on == ("s2", "s3")


def test_company_routes_cross_department_plan_by_tool_owner():
    plan = [
        PlannedAction("s1", "workspace_recursive_inventory", "list_files_recursive", {}, (), ("e",)),
        PlannedAction("s2", "cross_department_data_move", "analyze_csv_collection", {}, ("s1",), ("e",)),
        PlannedAction("s3", "cross_department_data_move", "move_workspace_file", {}, ("s2",), ("e",)),
        PlannedAction("s4", "cross_department_data_move", "create_company_data_report", {}, ("s2", "s3"), ("e",)),
        PlannedAction("s5", "file_read", "read_file", {}, ("s4",), ("e",)),
    ]
    assignments = DEFAULT_COMPANY.route_plan("cross-department data workflow", plan)
    assert [a.department for a in assignments] == ["operations", "data", "operations", "data", "operations"]
    assert assignments[1].specialist == "data:data-analyst"
    assert "security:reviewer" in assignments[2].reviewers


def test_independent_company_qa_requires_verified_cross_department_handoff():
    from app.organization.review import review_company_execution
    from types import SimpleNamespace
    plan = SimpleNamespace(steps=[
        SimpleNamespace(id="s1", tool="list_files_recursive", status="done", output={"ok": True}),
        SimpleNamespace(id="s2", tool="analyze_csv_collection", status="done", output={"verified": True, "selected_path": "sales.csv", "selected": {"numeric_total_sum": 100.0}, "count": 1}),
        SimpleNamespace(id="s3", tool="move_workspace_file", status="done", output={"verified": True, "fingerprint_match": True, "destination_exists": True, "unchanged_files_verified": True, "destination": "processed_data/sales.csv", "sha256_before": "abc", "sha256_after": "abc"}),
        SimpleNamespace(id="s4", tool="create_company_data_report", status="done", output={"verified": True, "report_reread_verified": True}),
        SimpleNamespace(id="s5", tool="read_file", status="done", output={"content": "sales.csv processed_data/sales.csv abc"}),
    ])
    assignments = [
        {"department": "operations", "operation": "cross_department_data_move", "reviewers": ["qa:reviewer"]},
        {"department": "data", "operation": "cross_department_data_move", "reviewers": ["qa:reviewer"]},
        {"department": "operations", "operation": "cross_department_data_move", "reviewers": ["security:reviewer", "qa:reviewer"]},
        {"department": "operations", "operation": "cross_department_data_move", "reviewers": ["qa:reviewer"]},
        {"department": "operations", "operation": "file_read", "reviewers": ["qa:reviewer"]},
    ]
    review = review_company_execution(goal="cross", operation="cross_department_data_move", plan=plan, assignments=assignments, status="completed")
    assert review.ok, review.to_dict()


def test_independent_company_qa_blocks_unverified_handoff():
    from app.organization.review import review_company_execution
    from types import SimpleNamespace
    plan = SimpleNamespace(steps=[SimpleNamespace(id="s1", tool="analyze_csv_collection", status="done", output={"verified": True, "selected_path": "sales.csv", "selected": {"numeric_total_sum": 100.0}})])
    assignments = [{"department": "data", "operation": "cross_department_data_move", "reviewers": ["qa:reviewer"]}]
    review = review_company_execution(goal="cross", operation="cross_department_data_move", plan=plan, assignments=assignments, status="completed")
    assert review.ok is False
    assert "required_tools_present" in review.reason

from types import SimpleNamespace

from app.brain.models import CandidateAction, SemanticFrame
from app.brain.methods import _cross_department_sales_report_move
from app.organization import DEFAULT_COMPANY
from app.organization.review import review_company_execution
from app.domain.plan import resolve


def test_sales_average_method_builds_cross_department_workflow():
    frame = SemanticFrame(
        text='analyze recursive CSV files, choose highest average sales, create report, move report to selected_reports and verify',
        language='en', speech_act='command', concepts=(),
        requested_operation='cross_department_sales_report_move',
    )
    tools = [
        ('list_files_recursive', 'workspace_recursive_inventory'),
        ('analyze_csv_by_average', 'cross_department_sales_report_move'),
        ('create_sales_analysis_report', 'cross_department_sales_report_move'),
        ('move_workspace_report', 'cross_department_sales_report_move'),
        ('read_file', 'file_read'),
    ]
    candidates = [CandidateAction(capability=c, tool=t, score=10, reason='test', requires_input=(),
                                  reversible=True, preconditions=(), effects=('effect',), risk='low', cost=1.0)
                  for t, c in tools]
    plan = _cross_department_sales_report_move(frame, candidates)
    assert [step.tool for step in plan] == [
        'list_files_recursive', 'analyze_csv_by_average', 'create_sales_analysis_report',
        'move_workspace_report', 'read_file'
    ]
    assert plan[2].args['output_path'] == 'top_sales_analysis.md'
    assert plan[2].args['destination_dir'] == 'selected_reports'
    assert plan[3].args['source_path'] == 'top_sales_analysis.md'
    assert plan[4].args['path'] == '{{s4.destination}}'



def test_structured_reference_resolves_actual_move_destination():
    from app.brain.kernel import CognitiveKernel
    outputs = {
        's4': {
            'source': 'top_sales_analysis.md',
            'destination': 'selected_reports/top_sales_analysis__2.md',
            'fingerprint_match': True,
        }
    }
    assert resolve({'path': '{{s4.destination}}'}, outputs)['path'] == 'selected_reports/top_sales_analysis__2.md'



def test_sales_workflow_rereads_unique_destination_when_target_already_exists(tmp_path, monkeypatch):
    import csv
    from app.runtime.registry import load_tools

    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path))
    (tmp_path / "selected_reports").mkdir()

    def write_csv(path, values):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["item", "sales"])
            writer.writeheader()
            for i, value in enumerate(values, 1):
                writer.writerow({"item": i, "sales": value})

    write_csv(tmp_path / "sales.csv", [10, 20, 30])
    write_csv(tmp_path / "other.csv", [5, 6, 7])
    existing = tmp_path / "selected_reports" / "top_sales_analysis.md"
    existing.write_text("preexisting report", encoding="utf-8")

    registry = load_tools()
    snapshot = registry["list_files_recursive"].run(path=".", exclude_path="top_sales_analysis.md").data
    analysis = registry["analyze_csv_by_average"].run(file_list=snapshot, question="choose highest average sales").data
    registry["create_sales_analysis_report"].run(analysis_result=analysis, output_path="top_sales_analysis.md", destination_dir="selected_reports")
    move = registry["move_workspace_report"].run(source_path="top_sales_analysis.md", destination_dir="selected_reports").data

    planned_path = "{{s4.destination}}"
    resolved_path = resolve({"path": planned_path}, {"s4": move})["path"]
    reread = registry["read_file"].run(path=resolved_path).data

    assert move["destination"] == "selected_reports/top_sales_analysis__2.md"
    assert move["fingerprint_match"] is True
    assert reread["path"] == move["destination"]
    assert (tmp_path / move["destination"]).is_file()
    assert existing.read_text(encoding="utf-8") == "preexisting report"

    steps = [
        SimpleNamespace(id="s1", tool="list_files_recursive", status="done", output=snapshot),
        SimpleNamespace(id="s2", tool="analyze_csv_by_average", status="done", output=analysis),
        SimpleNamespace(id="s3", tool="create_sales_analysis_report", status="done", output={"verified": True, "report_reread_verified": True, "path": "top_sales_analysis.md"}),
        SimpleNamespace(id="s4", tool="move_workspace_report", status="done", output=move),
        SimpleNamespace(id="s5", tool="read_file", status="done", output=reread),
    ]
    outputs = {step.id: step.output for step in steps}
    assignments = [
        {"department": "operations", "operation": "cross_department_sales_report_move", "reviewers": ["qa:reviewer"]},
        {"department": "data", "operation": "cross_department_sales_report_move", "reviewers": ["qa:reviewer"]},
        {"department": "data", "operation": "cross_department_sales_report_move", "reviewers": ["qa:reviewer"]},
        {"department": "operations", "operation": "cross_department_sales_report_move", "reviewers": ["security:reviewer", "qa:reviewer"]},
        {"department": "operations", "operation": "file_read", "reviewers": ["qa:reviewer"]},
    ]
    review = review_company_execution(
        goal="collision case", operation="cross_department_sales_report_move",
        plan=SimpleNamespace(steps=steps), assignments=assignments, status="completed", outputs=outputs,
    )
    assert review.ok, review.to_dict()


def test_company_routes_new_workflow_by_tool_owner():
    plan = SimpleNamespace(steps=[
        SimpleNamespace(step_id='s1', capability='workspace_recursive_inventory', tool='list_files_recursive', skill_key='builtin:workspace-recursive-inventory'),
        SimpleNamespace(step_id='s2', capability='cross_department_sales_report_move', tool='analyze_csv_by_average', skill_key='builtin:data-analysis'),
        SimpleNamespace(step_id='s3', capability='cross_department_sales_report_move', tool='create_sales_analysis_report', skill_key='builtin:data-analysis-report'),
        SimpleNamespace(step_id='s4', capability='cross_department_sales_report_move', tool='move_workspace_report', skill_key=''),
        SimpleNamespace(step_id='s5', capability='file_read', tool='read_file', skill_key=''),
    ])
    assignments = DEFAULT_COMPANY.route_plan('sales average report', plan)
    assert [a.department for a in assignments] == ['operations', 'data', 'data', 'operations', 'operations']
    assert assignments[2].specialist == 'data:data-analyst'
    assert 'security:reviewer' in assignments[3].reviewers


def test_sales_workflow_qa_accepts_verified_evidence():
    plan = SimpleNamespace(steps=[
        SimpleNamespace(step_id='s1', tool='list_files_recursive', status='done', output={'ok': True}),
        SimpleNamespace(step_id='s2', tool='analyze_csv_by_average', status='done', output={
            'verified': True, 'selection_metric': 'average', 'selected_path': 'sales.csv',
            'selected': {'selected_column': 'sales', 'average': 20.0, 'total': 100.0, 'maximum': 30.0, 'minimum': 10.0, 'source_fingerprint': 'hash1'},
            'files': [{'path': 'sales.csv', 'average': 20.0, 'total': 100.0, 'maximum': 30.0, 'minimum': 10.0, 'selected_column': 'sales', 'source_fingerprint': 'hash1'}],
            'count': 1,
        }),
        SimpleNamespace(step_id='s3', tool='create_sales_analysis_report', status='done', output={'verified': True, 'report_reread_verified': True}),
        SimpleNamespace(step_id='s4', tool='move_workspace_report', status='done', output={'verified': True, 'fingerprint_match': True, 'destination_exists': True, 'source_removed': True, 'destination': 'selected_reports/top_sales_analysis.md', 'sha256_before': 'hash1', 'sha256_after': 'hash1'}),
        SimpleNamespace(step_id='s5', tool='read_file', status='done', output={'content': 'sales.csv selected_reports/top_sales_analysis.md hash1 20.0 100.0 30.0 10.0'}),
    ])
    assignments = [
        {'department':'operations','operation':'cross_department_sales_report_move','reviewers':['qa:reviewer']},
        {'department':'data','operation':'cross_department_sales_report_move','reviewers':['qa:reviewer']},
        {'department':'operations','operation':'cross_department_sales_report_move','reviewers':['qa:reviewer']},
        {'department':'operations','operation':'cross_department_sales_report_move','reviewers':['security:reviewer','qa:reviewer']},
        {'department':'operations','operation':'file_read','reviewers':['qa:reviewer']},
    ]
    review = review_company_execution(goal='cross', operation='cross_department_sales_report_move', plan=plan, assignments=assignments, status='completed')
    assert review.ok, review.to_dict()


def test_semantic_router_types_sales_average_report_goal(monkeypatch):
    import app.intelligence.semantic.parser as parser
    goal = "افحص ملفات CSV في workspace بشكل recursive واختر ملف المبيعات صاحب أعلى متوسط sales وأنشئ تقريرًا ثم انقله إلى selected_reports وتحقق منه."
    monkeypatch.setattr(parser, "candidates", lambda _text: [])
    monkeypatch.setattr(parser, "apply_brain_priors", lambda _original, base, _registry, speech_act: base)
    parsed = parser.semantic_understand(goal, mem=None, world={}, registry={})
    assert parsed.top_intent is not None
    assert parsed.top_intent.name == "cross_department_sales_report_move"
    assert not parsed.needs_clarification


def test_sales_workflow_qa_normalizes_windows_reread_path():
    plan = SimpleNamespace(steps=[
        SimpleNamespace(step_id='s1', tool='list_files_recursive', status='done', output={'ok': True}),
        SimpleNamespace(step_id='s2', tool='analyze_csv_by_average', status='done', output={
            'verified': True, 'selection_metric': 'average', 'selected_path': 'sales.csv',
            'selected': {'selected_column': 'sales', 'average': 20.0, 'total': 100.0, 'maximum': 30.0, 'minimum': 10.0, 'source_fingerprint': 'hash1'},
            'files': [{'path': 'sales.csv', 'average': 20.0, 'total': 100.0, 'maximum': 30.0, 'minimum': 10.0, 'selected_column': 'sales', 'source_fingerprint': 'hash1'}],
            'count': 1,
        }),
        SimpleNamespace(step_id='s3', tool='create_sales_analysis_report', status='done', output={'verified': True, 'report_reread_verified': True}),
        SimpleNamespace(step_id='s4', tool='move_workspace_report', status='done', output={
            'verified': True, 'fingerprint_match': True, 'destination_exists': True, 'source_removed': True,
            'destination': 'selected_reports/top_sales_analysis.md', 'sha256_before': 'hash1', 'sha256_after': 'hash1',
        }),
        SimpleNamespace(step_id='s5', tool='read_file', status='done', output={
            'path': r'selected_reports\top_sales_analysis.md',
            'content': 'sales.csv selected_reports/top_sales_analysis.md hash1 20.0 100.0 30.0 10.0',
        }),
    ])
    assignments = [
        {'department':'operations','operation':'cross_department_sales_report_move','reviewers':['qa:reviewer']},
        {'department':'data','operation':'cross_department_sales_report_move','reviewers':['qa:reviewer']},
        {'department':'data','operation':'cross_department_sales_report_move','reviewers':['qa:reviewer']},
        {'department':'operations','operation':'cross_department_sales_report_move','reviewers':['security:reviewer','qa:reviewer']},
        {'department':'operations','operation':'file_read','reviewers':['qa:reviewer']},
    ]
    review = review_company_execution(
        goal='windows path regression', operation='cross_department_sales_report_move',
        plan=plan, assignments=assignments, status='completed',
    )
    assert review.ok, review.to_dict()


def test_read_file_emits_posix_workspace_relative_path(tmp_path, monkeypatch):
    from app.runtime.registry import load_tools

    monkeypatch.setenv('AGENT_WORKSPACE', str(tmp_path))
    target = tmp_path / 'selected_reports' / 'top_sales_analysis.md'
    target.parent.mkdir(parents=True)
    target.write_text('report', encoding='utf-8')

    result = load_tools()['read_file'].run(path='selected_reports/top_sales_analysis.md').data
    assert result['path'] == 'selected_reports/top_sales_analysis.md'

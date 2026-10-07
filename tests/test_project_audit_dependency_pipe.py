from types import SimpleNamespace


def test_exact_step_reference_preserves_structured_output():
    from app.brain.kernel import CognitiveKernel
    from app.brain.models import PlannedAction

    kernel = CognitiveKernel.__new__(CognitiveKernel)
    kernel.registry = {'consumer': SimpleNamespace(pipe_param=None)}
    action = PlannedAction('s2', 'consumer', 'consumer', {'payload': '{{s1}}'}, ('s1',))
    payload = {'attempted': 2, 'passed': 1, 'failed': 1}

    resolved = kernel._resolve_action_args(action, {'s1': payload})
    assert resolved['payload'] == payload
    assert isinstance(resolved['payload'], dict)


def test_tool_pipe_param_receives_latest_dependency():
    from app.brain.kernel import CognitiveKernel
    from app.brain.models import PlannedAction

    kernel = CognitiveKernel.__new__(CognitiveKernel)
    kernel.registry = {'report': SimpleNamespace(pipe_param='test_audit')}
    action = PlannedAction('s4', 'project_audit', 'report', {}, ('s3',))
    payload = {'attempted': 2, 'passed': 1, 'failed': 1}

    resolved = kernel._resolve_action_args(action, {'s3': payload})
    assert resolved['test_audit'] == payload


def test_project_audit_skill_declares_dependency_pipe_contract():
    from app.skills.builtin import BUILTIN_SKILLS
    from app.runtime.registry import load_tools

    spec = next(item for item in BUILTIN_SKILLS if item['key'] == 'builtin:project-audit')
    s3 = next(item for item in spec['workflow'] if item['step_id'] == 's3')
    s4 = next(item for item in spec['workflow'] if item['step_id'] == 's4')
    tools = load_tools()

    assert s3['tool'] == 'audit_project_tests'
    assert s4['tool'] == 'create_project_audit_report'
    assert tools[s4['tool']].pipe_param == 'test_audit'
    assert 's3' in s4['depends_on']
    assert tools[s3['tool']].pipe_source is True


def test_report_tool_accepts_structured_test_audit_payload(tmp_path, monkeypatch):
    from app.runtime.registry import load_tools

    monkeypatch.setenv('AGENT_WORKSPACE', str(tmp_path))
    (tmp_path / 'requirements.txt').write_text('pytest\n', encoding='utf-8')
    (tmp_path / 'demo.py').write_text("print('ok')\n", encoding='utf-8')
    audit_payload = {
        'path': str(tmp_path),
        'commands': [['python', '-m', 'compileall', '-q', '.']],
        'results': [{'command': ['python', '-m', 'compileall', '-q', '.'], 'returncode': 0, 'ok': True, 'stdout': '', 'stderr': ''}],
        'attempted': 1,
        'passed': 1,
        'failed': 0,
        'all_passed': True,
    }
    tool = load_tools()['create_project_audit_report']
    result = tool.run(path='.', output_path='shury_project_audit.md', question='audit', test_audit=audit_payload)
    assert result.ok
    assert result.data['verified'] is True


def test_builtin_skill_bootstrap_refreshes_existing_stale_contract(tmp_path):
    from app.skills.registry import SkillBank
    from app.skills.builtin import BUILTIN_SKILLS
    import sqlite3, json

    path = tmp_path / 'skills.db'
    bank = SkillBank(path, bootstrap=False)
    spec = next(item for item in BUILTIN_SKILLS if item['key'] == 'builtin:project-audit')
    bank.upsert(**{**spec, 'workflow': (dict(spec['workflow'][0]),)})
    conn = sqlite3.connect(path)
    try:
        workflow = list(spec['workflow'])
        workflow_json = json.dumps(workflow, ensure_ascii=False, default=str)
        conn.execute('UPDATE skills SET workflow=?, source=? WHERE key=?', (workflow_json, 'builtin', spec['key']))
        conn.commit()
    finally:
        conn.close()

    refreshed = SkillBank(path, bootstrap=True).get('builtin:project-audit')
    final_tools = [item.get('tool') for item in refreshed.workflow]
    assert final_tools == ['inspect_project', 'git_status', 'audit_project_tests', 'create_project_audit_report']
    s4 = refreshed.workflow[-1]
    assert 's3' in tuple(s4.get('depends_on') or ())
    assert s4.get('args', {}).get('test_audit') == '{{s3}}'


def test_pipe_param_empty_placeholder_is_filled_from_dependency():
    from app.brain.kernel import CognitiveKernel
    from app.brain.models import PlannedAction
    kernel = CognitiveKernel.__new__(CognitiveKernel)
    kernel.registry = {'report': SimpleNamespace(pipe_param='test_audit')}
    action = PlannedAction('s4', 'project_audit', 'report', {'test_audit': ''}, ('s3',))
    payload = {'attempted': 2, 'passed': 2, 'failed': 0}
    resolved = kernel._resolve_action_args(action, {'s3': payload})
    assert resolved['test_audit'] == payload


def test_project_audit_report_path_can_live_in_workspace_separate_from_project(tmp_path, monkeypatch):
    from app.runtime.registry import load_tools
    monkeypatch.setenv('AGENT_PROJECT_ROOT', str(tmp_path))
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    monkeypatch.setenv('AGENT_WORKSPACE', str(workspace))
    (tmp_path / 'requirements.txt').write_text('pytest\n', encoding='utf-8')
    (tmp_path / 'demo.py').write_text("print('ok')\n", encoding='utf-8')
    audit_payload = {'attempted': 1, 'passed': 1, 'failed': 0, 'all_passed': True, 'results': [], 'commands': []}
    tool = load_tools()['create_project_audit_report']
    result = tool.run(path='.', output_path='workspace/audit.md', question='audit', test_audit=audit_payload)
    assert result.ok, result.error
    assert result.data['verified'] is True
    assert (workspace / 'audit.md').is_file()

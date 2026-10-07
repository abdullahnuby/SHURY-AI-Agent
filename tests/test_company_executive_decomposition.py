from app.organization import DEFAULT_COMPANY, ExecutiveDecomposer
from app.organization.models import CompanyAssignment, CompanyTask


def _assignment(step_id, department, head, specialist, *, depends=(), reviewers=('qa:reviewer',)):
    return CompanyAssignment(
        objective='generic executive goal', operation='capability-x', skill_key='',
        chief_executive='executive:chief-executive', department=department,
        department_head=head, specialist=specialist, reviewers=reviewers,
        step_id=step_id, tool=f'tool-{step_id}', capability='capability-x',
        depends_on=tuple(depends), expected_effects=('effect-x',),
    )


def test_decomposer_is_operation_name_independent_and_builds_waves():
    assignments = [
        _assignment('s1', 'data', 'data:head', 'data:data-analyst'),
        _assignment('s2', 'operations', 'operations:head', 'operations:file-specialist'),
        _assignment('s3', 'research', 'research:head', 'research:research-analyst', depends=('company:s1', 'company:s2')),
    ]
    coordination = DEFAULT_COMPANY.decompose('a goal with no workflow name', assignments)

    assert coordination.validation_errors == ()
    assert coordination.execution_waves[0].task_ids == ('company:s1', 'company:s2')
    assert coordination.execution_waves[1].task_ids == ('company:s3',)
    assert coordination.critical_path in (('company:s1', 'company:s3'), ('company:s2', 'company:s3'))
    assert {row.department for row in coordination.workstreams} == {'data', 'operations', 'research'}
    assert len(coordination.handoffs) == 2


def test_decomposer_blocks_unknown_dependency_and_cycle():
    unknown = (CompanyTask(
        task_id='a', objective='a', department='data', department_head='data:head', specialist='data:data-analyst',
        step_id='a', tool='a', depends_on=('missing',),
    ),)
    result = ExecutiveDecomposer().decompose(unknown)
    assert result.valid is False
    assert 'unknown_dependency:a:missing' in result.errors

    cyclic = (
        CompanyTask(task_id='a', objective='a', department='data', department_head='data:head', specialist='data:data-analyst', step_id='a', tool='a', depends_on=('b',)),
        CompanyTask(task_id='b', objective='b', department='operations', department_head='operations:head', specialist='operations:file-specialist', step_id='b', tool='b', depends_on=('a',)),
    )
    result = ExecutiveDecomposer().decompose(cyclic)
    assert result.valid is False
    assert 'dependency_cycle' in result.errors


def test_canonical_brain_exposes_executive_decomposition_event():
    from app.brain import CognitiveKernel
    payload = {
        'goal': 'analyze dataset', 'operation': 'data_analysis', 'capability': 'data_analysis',
        'target': '', 'target_type': '', 'slots': {'path': 'workspace/sales.csv'},
        'constraints': [], 'temporal_requirements': [], 'required_evidence': [],
        'priority': 0.5, 'language': 'en',
    }
    result = CognitiveKernel().think_structured(payload)
    events = [e for e in result.state.trace if e.get('kind') == 'company_executive_decomposition']
    assert events
    assert events[-1]['execution_waves']
    assert events[-1]['critical_path']

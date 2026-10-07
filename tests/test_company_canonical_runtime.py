from app.brain import CognitiveKernel
from app.intelligence.semantic.models import SemanticParse


def test_structured_canonical_runtime_records_company_delegation():
    kernel = CognitiveKernel()
    payload = {
        'goal': 'analyze dataset',
        'operation': 'data_analysis',
        'capability': 'data_analysis',
        'target': '',
        'target_type': '',
        'slots': {'path': 'workspace/sales.csv'},
        'constraints': [],
        'temporal_requirements': [],
        'required_evidence': [],
        'priority': 0.5,
        'language': 'en',
    }
    result = kernel.think_structured(payload)
    events = [e for e in result.state.trace if e.get('kind') == 'company_delegation']
    assert events, result.state.trace
    event = events[-1]
    assert event['department'] == 'data'
    assert event['department_head'] == 'data:head'
    assert event['specialist'] == 'data:data-analyst'
    assert event['reviewers'] == ['qa:reviewer']

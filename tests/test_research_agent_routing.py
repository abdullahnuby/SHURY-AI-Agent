from types import SimpleNamespace
from pathlib import Path


def test_external_research_cannot_become_project_audit(monkeypatch):
    from app.intelligence.semantic import intents
    from app.intelligence.semantic import parser as parser_mod

    class U:
        intents = []

    monkeypatch.setattr(intents, 'understand', lambda text: U())
    monkeypatch.setattr(
        intents,
        'rank_query_against_texts',
        lambda text, rows, top_k: [
            SimpleNamespace(name='project_audit::0', score=0.99),
            SimpleNamespace(name='open_world_learning::0', score=0.25),
        ],
    )

    from app.intelligence.semantic.models import SemanticParse
    # Parser construction only; use the real parser helpers with retrieval mocked.
    parsed = parser_mod.semantic_understand(
        'ابحث على الإنترنت عن أحدث أبحاث Long-Term Memory للـAI Agents وقارن بينها واحفظ تقريرًا في workspace/agent_memory_research.md'
    )
    assert parsed.top_intent.name == 'research_report'
    assert parsed.top_intent.capability == 'research'
    assert all(x.name != 'project_audit' for x in parsed.intent_candidates)


def test_research_report_skill_exists_and_is_two_step():
    from app.skills.builtin import BUILTIN_SKILLS
    spec = next(x for x in BUILTIN_SKILLS if x['key'] == 'builtin:research-report')
    assert [step['tool'] for step in spec['workflow']] == ['internet_research', 'create_research_report']
    assert spec['workflow'][1]['depends_on'] == ('s1',)
    assert spec['workflow'][1]['args']['research_result'] == '{{s1}}'

def test_research_report_skill_expands_to_research_and_report(tmp_path):
    from app.brain.models import CognitiveState, SemanticFrame
    from app.brain.planner import make_goal, plan
    from app.brain.capabilities import discover_candidates, discover_skill_candidates
    from app.runtime.registry import load_tools
    from app.skills.registry import SkillBank

    text = 'ابحث على الإنترنت عن أحدث أبحاث Long-Term Memory للـAI Agents وقارن بينها واحفظ تقريرًا في workspace/agent_memory_research.md'
    frame = SemanticFrame(
        text=text, language='mixed', speech_act='instruction', concepts=('research_report',),
        requested_operation='research_report', slots=(), uncertainty=()
    )
    goal = make_goal(frame)
    assert goal.required_capability == 'research_report'

    bank = SkillBank(tmp_path / 'skills.db', bootstrap=True)
    skills = discover_skill_candidates(goal, frame, bank)
    assert skills and skills[0].key == 'builtin:research-report'

    registry = load_tools()
    candidates = discover_candidates(frame, registry)
    state = CognitiveState(user_text=text, semantic=frame, goal=goal)
    state.selected_skill = skills[0]
    actions = plan(goal, frame, candidates, state=state, registry=registry)
    assert [a.tool for a in actions] == ['internet_research', 'create_research_report']
    assert actions[1].depends_on == ('s1',)

def test_research_report_tool_writes_and_verifies_artifact(tmp_path, monkeypatch):
    from app.tools.research.report import create_research_report
    import os

    monkeypatch.setenv('AGENT_WORKSPACE', str(tmp_path))
    result = {
        'providers': ['web', 'arxiv', 'github'],
        'arxiv': {'papers': [
            {'title': f'Paper {i}', 'authors': ['A'], 'published': f'2026-0{i+1}-01T00:00:00+00:00',
             'url': f'https://arxiv.org/abs/1234.{i}',
             'abstract': 'temporal episodic memory with hybrid retrieval, forgetting, and experience learning.'}
            for i in range(5)
        ]},
    }
    wrapped = create_research_report.run(research_result=result, output_path='agent_memory_research.md', question='research')
    assert wrapped.ok is True
    assert wrapped.data['verified'] is True
    out = Path(tmp_path) / 'agent_memory_research.md'
    assert out.exists()
    text = out.read_text(encoding='utf-8')
    assert 'Top 5 Recent Papers' in text
    assert 'Comparison' in text
    assert 'SHURY Fit' in text

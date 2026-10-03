from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from app.brain.models import CandidateAction, CognitiveState, PlannedAction


StepBuilder = Callable[[Any, list[CandidateAction]], list[PlannedAction]]


@dataclass(frozen=True)
class Method:
    """A language-independent way to achieve a goal.

    Methods are procedural knowledge. They are deliberately separate from
    semantic parsing and from individual tool implementations.
    """

    name: str
    operations: tuple[str, ...]
    priority: float
    builder: StepBuilder
    description: str = ''

    def applicable(self, operation: str, frame: Any, candidates: list[CandidateAction],
                   state: CognitiveState | None = None) -> bool:
        if operation not in self.operations:
            return False
        return bool(self.builder(frame, candidates))

    def build(self, frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
        return self.builder(frame, candidates)


def _pick(candidates: Iterable[CandidateAction], *, tools: tuple[str, ...] = (),
          capabilities: tuple[str, ...] = ()) -> CandidateAction | None:
    tool_set = set(tools)
    cap_set = set(capabilities)
    matches = [c for c in candidates if c.tool in tool_set or c.capability in cap_set]
    matches.sort(key=lambda x: (-x.score, x.cost, x.tool))
    return matches[0] if matches else None


def _pick_preferred(candidates: Iterable[CandidateAction], preferred_tools: tuple[str, ...]) -> CandidateAction | None:
    """Respect semantic/source constraints before learned score tie-breaking."""
    by_tool: dict[str, list[CandidateAction]] = {}
    for candidate in candidates:
        by_tool.setdefault(candidate.tool, []).append(candidate)
    for tool in preferred_tools:
        matches = by_tool.get(tool, [])
        if matches:
            matches.sort(key=lambda x: (-x.score, x.cost, x.tool))
            return matches[0]
    return None


def _single(frame: Any, candidates: list[CandidateAction], *,
            tools: tuple[str, ...] = (), capabilities: tuple[str, ...] = (),
            args: Callable[[Any, CandidateAction], dict[str, Any]] | None = None,
            rationale: str = '') -> list[PlannedAction]:
    c = _pick(candidates, tools=tools, capabilities=capabilities)
    if not c:
        return []
    return [PlannedAction(
        's1', c.capability, c.tool,
        args(frame, c) if args else {}, (), c.effects, rationale or f'use {c.tool} for the goal',
    )]


def _calculate(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    if not frame.slot('expression'):
        return []
    return _single(
        frame, candidates, tools=('calculator',), capabilities=('calculate',),
        args=lambda f, _c: {'expression': f.slot('expression')},
        rationale='establish a deterministic numeric result',
    )


def _remember(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    if not frame.slot('predicate') or not frame.slot('value'):
        return []
    return _single(
        frame, candidates, tools=('remember_fact',), capabilities=('remember_fact',),
        args=lambda f, _c: {'key': f.slot('predicate'), 'value': f.slot('value')},
        rationale='persist an explicit user-provided belief',
    )


def _forget_memory(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    key = frame.slot('key') or frame.slot('predicate')
    if not key:
        return []
    c = _pick(candidates, tools=('forget_fact',), capabilities=('forget_fact',))
    if not c:
        return []
    return [PlannedAction('s1', c.capability, c.tool, {'key': str(key)}, (), c.effects,
                          'delete the requested durable memory through the canonical memory authority')]


def _identity(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    return _single(
        frame, candidates, tools=('recall_fact',), capabilities=('recall_fact',),
        args=lambda f, _c: {'key': f.slot('key') or f.slot('predicate') or 'name'},
        rationale='retrieve the requested identity belief from durable memory',
    )


def _memory_query(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    key = frame.slot('key') or frame.slot('predicate')
    if key:
        c = _pick_preferred(candidates, ('recall_fact', 'memory_search'))
    else:
        c = _pick(candidates, tools=('memory_search', 'memory_profile'), capabilities=('memory_search', 'memory_profile'))
    if not c:
        return []
    query = key or frame.slot('query') or frame.text
    if c.tool == 'memory_search':
        args = {'query': query}
    elif c.tool == 'recall_fact':
        args = {'key': query}
    else:
        args = {}
    return [PlannedAction('s1', c.capability, c.tool, args, (), c.effects, 'retrieve evidence from durable memory')]


def _knowledge(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    preferred = {'research_memory_search', 'answer_question', 'agentic_rag'}
    eligible = [c for c in candidates if c.tool in preferred]
    if not eligible:
        return []
    # Candidate scores already contain verified experience and contextual self-model
    # adjustments. The method still constrains the route to grounded knowledge tools,
    # but it must not throw away learned evidence by using a fixed tool ordering.
    c = max(eligible, key=lambda item: (float(item.score), -float(item.cost), item.tool))
    query = frame.slot('query') or frame.text
    return [PlannedAction('s1', c.capability, c.tool, {'query': query}, (), c.effects,
                          'acquire grounded evidence before answering')]


def _research(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    text = str(getattr(frame, 'text', '') or '').casefold()
    explicit_external = any(marker in text for marker in (
        'from web', 'from the web', 'from internet', 'from the internet',
        'search online', 'search the internet', 'on the web', 'on the internet',
        'الويب', 'الإنترنت', 'الانترنت', 'اونلاين', 'أونلاين',
    ))
    concepts = set(frame.concepts or ())
    learning_requested = bool(concepts & {'learning', 'open_world_learning', 'learning_intent'})
    if learning_requested and explicit_external:
        preferred = ('research_and_learn', 'internet_research', 'web_research')
    elif explicit_external:
        preferred = ('web_research', 'internet_research', 'research_and_learn')
    elif learning_requested:
        preferred = ('research_and_learn', 'research_memory_search', 'internet_research', 'web_research', 'agentic_rag', 'answer_question')
    elif any(marker in text for marker in ('stored', 'memory', 'saved', 'knowledge base', 'محفوظ', 'ذاكرة')):
        preferred = ('research_memory_search', 'agentic_rag', 'internet_research', 'web_research', 'answer_question')
    else:
        preferred = ('research_memory_search', 'agentic_rag', 'internet_research', 'web_research', 'answer_question')
    c = _pick_preferred(candidates, preferred)
    if not c:
        return []
    query = frame.slot('query') or frame.text
    return [PlannedAction('s1', c.capability, c.tool, {'query': query}, (), c.effects,
                          'research until evidence satisfies the answer gate; reuse verified evidence for future learning')]


def _inspect_project(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    c = _pick_preferred(candidates, ('inspect_project',))
    if not c:
        return []
    path = frame.slot('path') or '.'
    return [PlannedAction('s1', c.capability, c.tool, {'path': path}, (), c.effects,
                          'inspect the project deterministically before drawing conclusions')]


def _time(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    return _single(frame, candidates, tools=('get_time',), capabilities=('time',), rationale='observe current time directly')



def _data_analysis(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    text = str(getattr(frame, 'text', '') or '')
    lowered = text.casefold()
    profile = any(marker in lowered for marker in ("profile dataset", "dataset profile", "profile the data", "profile the dataset", "بروفايل", "schema"))
    tool_names = ('profile_dataset', 'analyze_dataset') if profile else ('analyze_dataset', 'profile_dataset')
    c = _pick(candidates, tools=tool_names, capabilities=('data_analysis',))
    if not c:
        return []
    import re
    match = re.search(r'[^\s]+\.(?:csv|json|sqlite3?|db)\b', text, re.I)
    path = match.group(0) if match else (frame.slot('path') or '@active_dataset')
    if c.tool == 'profile_dataset':
        args = {'path': path}
        rationale = 'profile the selected dataset using the deterministic data-analysis tool'
    else:
        args = {'path': path, 'question': text}
        rationale = 'analyze the selected dataset using reproducible local evidence'
    return [PlannedAction('s1', c.capability, c.tool, args, (), c.effects, rationale)]

def _skills(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    # A request for skills *for a task* is a selection problem, not an inventory query.
    if frame.question_type == 'skill_selection' or frame.slot('query'):
        c = _pick(candidates, tools=('match_skills',), capabilities=('skill_selection',))
        if c:
            return [PlannedAction('s1', c.capability, c.tool, {'goal': frame.slot('query') or frame.text}, (), c.effects,
                                  'select procedures applicable to the requested task')]
    c = _pick(candidates, tools=('list_skills',), capabilities=('skill_management',))
    if c:
        return [PlannedAction('s1', c.capability, c.tool, {'status': 'approved'}, (), c.effects,
                              'inspect the procedural capability inventory')]
    return []


def _compound(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    if not frame.slot('expression'):
        return []
    calc = _pick(candidates, tools=('calculator',), capabilities=('calculate',))
    save = _pick_preferred(candidates, ('remember_result', 'remember_fact'))
    if not calc or not save:
        return []
    key = frame.slot('result_key') or 'total'
    if save.tool == 'remember_result':
        args = {'key': key, 'value': '{{s1}}'}
    else:
        args = {'key': key, 'value': '{{s1}}'}
    return [
        PlannedAction('s1', calc.capability, calc.tool, {'expression': frame.slot('expression')}, (), calc.effects,
                      'create the source value before persisting it'),
        PlannedAction('s2', save.capability, save.tool, args, ('s1',), save.effects,
                      'persist only after the source value has been observed'),
    ]


_METHODS: tuple[Method, ...] = (
    Method('compound_calculate_and_remember', ('compound_calculate_remember',), 1.0, _compound,
           'calculate a value then persist the observed result'),
    Method('deterministic_calculation', ('calculate',), 1.0, _calculate,
           'perform a deterministic calculation'),
    Method('persist_user_belief', ('remember',), 1.0, _remember,
           'store explicit user information'),
    Method('forget_durable_memory', ('forget_memory',), 1.0, _forget_memory,
           'delete durable user memory through the canonical memory authority'),
    Method('retrieve_identity_belief', ('query_identity',), 1.0, _identity,
           'retrieve user identity from memory'),
    Method('retrieve_memory_evidence', ('query_memory',), 0.95, _memory_query,
           'search durable memory'),
    Method('inspect_project', ('development_inspection',), 1.0, _inspect_project,
           'inspect a project using the deterministic project inspection capability'),
    Method('grounded_knowledge_answer', ('query_knowledge',), 0.92, _knowledge,
           'acquire evidence for a knowledge question'),
    Method('external_research', ('research', 'learning_intent', 'open_world_learning'), 0.9, _research,
           'research using grounded retrieval'),
    Method('observe_current_time', ('query_time',), 1.0, _time,
           'read current time from the system'),
    Method('analyze_dataset', ('data_analysis',), 0.96, _data_analysis,
           'profile or analyze a local dataset with deterministic evidence'),
    Method('inspect_skill_inventory', ('skill_query',), 0.9, _skills,
           'inspect available procedural skills'),
)


class MethodRegistry:
    def __init__(self, methods: Iterable[Method] = _METHODS):
        self._methods = tuple(methods)

    def for_operation(self, operation: str) -> tuple[Method, ...]:
        return tuple(m for m in self._methods if operation in m.operations)

    def all(self) -> tuple[Method, ...]:
        return self._methods

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
    if frame.slot('result:reference') == 'previous':
        return _single(
            frame, candidates, tools=('recall_last_result',), capabilities=('recall_last_result',),
            rationale='retrieve the current session result through its scoped runtime state',
        )
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


def _data_analysis_report(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    c = _pick_preferred(candidates, ('create_data_analysis_report',))
    if not c:
        return []
    import re
    text = str(getattr(frame, 'text', '') or '')
    source = frame.slot('path')
    m = re.search(r'[^\s]+\.(?:csv|json|sqlite3?|db)\b', text, re.I)
    if not source and m:
        source = m.group(0)
    source = source or '@active_dataset'
    out = frame.slot('output_path')
    matches = list(re.finditer(r'[^\s,;!?؟]+\.(?:md|txt)\b', text, re.I))
    if matches:
        out = matches[-1].group(0).strip(' \t,.;!?؟')
    out = out or 'analysis_report.md'
    destination = str(frame.slot('destination_dir') or '').strip()
    if destination:
        from pathlib import Path
        out = str(Path(destination) / Path(out).name).replace('\\', '/')
    return [PlannedAction('s1', c.capability, c.tool, {'path': source, 'output_path': out, 'question': text}, (), c.effects,
                          'perform deterministic dataset analysis and create a verified artifact at the user-specified destination')]




def _research_report(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    first = _pick_preferred(candidates, ('internet_research', 'arxiv_research', 'research_and_learn', 'web_research'))
    create = _pick_preferred(candidates, ('create_research_report',))
    if not first or not create:
        return []
    import re
    from pathlib import Path
    text = str(getattr(frame, 'text', '') or '')
    matches = list(re.finditer(r'[^\s,;!?؟]+\.(?:md|txt)\b', text, re.I))
    out = matches[-1].group(0) if matches else (frame.slot('output_path') or 'research_report.md')
    actions = [PlannedAction('s1', first.capability, first.tool, {'query': text}, (), first.effects,
                              'collect fresh external research evidence before comparison')]
    actions.append(PlannedAction('s2', create.capability, create.tool, {'output_path': out, 'question': text, 'research_result': '{{s1}}'}, ('s1',), create.effects,
                                  'build and verify a structured research artifact from observed evidence'))
    return actions


def _project_audit(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    """Fallback project-audit plan when no persisted Skill is selected.

    The preferred production path is the first-class Skill contract. This fallback preserves
    capability availability while keeping the workflow explicit and verifiable.
    """
    create = _pick_preferred(candidates, ('create_project_audit_report',))
    if not create:
        return []
    return [PlannedAction('s1', create.capability, create.tool, {'path': frame.slot('path') or '.', 'output_path': frame.slot('output_path') or 'shury_project_audit.md', 'question': frame.text, 'test_audit': ''}, (), create.effects, 'create a verified project audit artifact from live repository evidence')]

def _workspace_inventory(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    list_tool = _pick_preferred(candidates, ('list_files',))
    create_tool = _pick_preferred(candidates, ('create_file_inventory',))
    read_tool = _pick_preferred(candidates, ('read_file',))
    if not list_tool or not create_tool or not read_tool:
        return []
    return [
        PlannedAction('s1', list_tool.capability, list_tool.tool, {'path': frame.slot('path') or '.'}, (), list_tool.effects,
                      'enumerate the current workspace before creating an inventory'),
        PlannedAction('s2', create_tool.capability, create_tool.tool,
                      {'output_path': 'file_inventory.md'}, ('s1',), create_tool.effects,
                      'create a deterministic inventory from the observed workspace snapshot', skill_key='builtin:workspace-inventory'),
        PlannedAction('s3', read_tool.capability, read_tool.tool, {'path': 'file_inventory.md'}, ('s2',), read_tool.effects,
                      'read the generated inventory and verify the artifact contents'),
    ]



def _workspace_recursive_inventory(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    list_tool = _pick_preferred(candidates, ('list_files_recursive',))
    create_tool = _pick_preferred(candidates, ('create_workspace_tree_inventory',))
    read_tool = _pick_preferred(candidates, ('read_file',))
    if not list_tool or not create_tool or not read_tool:
        return []
    import re
    text = str(getattr(frame, 'text', '') or '')
    matches = list(re.finditer(r'[^\s,;!?؟]+\.(?:md|txt)\b', text, re.I))
    out = matches[-1].group(0).strip(' \t,.;!?؟') if matches else 'workspace_inventory.md'
    return [
        PlannedAction('s1', list_tool.capability, list_tool.tool, {'path': '.', 'exclude_path': out}, (), list_tool.effects,
                      'observe the complete workspace tree before creating the inventory report'),
        PlannedAction('s2', create_tool.capability, create_tool.tool,
                      {'output_path': out}, ('s1',), create_tool.effects,
                      'derive folder statistics and largest-file ranking from one recursive snapshot and verify against the live filesystem', skill_key='builtin:workspace-recursive-inventory'),
        PlannedAction('s3', read_tool.capability, read_tool.tool, {'path': out}, ('s2',), read_tool.effects,
                      'reread the persisted recursive inventory so final state is grounded in the artifact'),
    ]



def _workspace_duplicate_cleanup(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    list_tool = _pick_preferred(candidates, ('list_files_recursive',))
    clean_tool = _pick_preferred(candidates, ('deduplicate_workspace_files',))
    read_tool = _pick_preferred(candidates, ('read_file',))
    if not list_tool or not clean_tool or not read_tool:
        return []
    import re
    text = str(getattr(frame, 'text', '') or '')
    suffix_matches = list(re.finditer(r'\S+\.(?:md|txt)\b', text, re.I))
    out = 'duplicate_cleanup_report.md'
    for m in reversed(suffix_matches):
        candidate = m.group(0).strip(' \t,.;!?؟')
        if 'duplicate' in candidate.casefold() or 'cleanup' in candidate.casefold() or 'تنظيف' in candidate:
            out = candidate.split('/', 1)[-1] if candidate.casefold().startswith('workspace/') else candidate
            break
    archive = 'duplicates_archive'
    archive_match = re.search(r'(?:workspace[\\/])?([A-Za-z0-9_-]*(?:duplicate|duplicates|archive)[A-Za-z0-9_-]*)', text, re.I)
    if archive_match and ('archive' in archive_match.group(1).casefold() or 'duplicates' in archive_match.group(1).casefold()):
        archive = archive_match.group(1)
    return [
        PlannedAction('s1', list_tool.capability, list_tool.tool,
                      {'path': '.', 'exclude_path': out}, (), list_tool.effects,
                      'observe one recursive workspace snapshot before duplicate analysis'),
        PlannedAction('s2', clean_tool.capability, clean_tool.tool,
                      {'output_path': out, 'archive_path': archive}, ('s1',), clean_tool.effects,
                      'hash file contents, group duplicate content, keep one canonical copy, and archive only the extras with integrity verification', skill_key='builtin:workspace-duplicate-cleanup'),
        PlannedAction('s3', read_tool.capability, read_tool.tool,
                      {'path': out}, ('s2',), read_tool.effects,
                      'reread the duplicate-cleanup report so final state is grounded in the persisted artifact'),
    ]


def _workspace_file_organization(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    import re
    text = str(getattr(frame, 'text', '') or '')
    n = text.casefold()
    move_action = bool(re.search(r"(?:انقل|حرك|حرّك|نقل|move|transfer|put)\b", n, re.I))
    if move_action:
        move_tool = _pick_preferred(candidates, ('move_workspace_report',))
        source = frame.slot('path')
        destination = frame.slot('destination_dir')
        if not move_tool or not source or not destination:
            return []
        # Use the semantic goal capability for the plan contract. The reusable move tool
        # happens to be owned by an older cross-department capability, but a direct file move
        # must be evaluated as a workspace-file-organization goal, not as a sales workflow.
        return [PlannedAction('s1', frame.requested_operation or 'workspace_file_organization', move_tool.tool,
                              {'source_path': source, 'destination_dir': destination}, (), move_tool.effects,
                              'move the explicitly resolved local file to the explicitly resolved destination and verify persistence')]

    list_tool = _pick_preferred(candidates, ('list_files',))
    organize_tool = _pick_preferred(candidates, ('organize_workspace_files',))
    read_tool = _pick_preferred(candidates, ('read_file',))
    if not list_tool or not organize_tool or not read_tool:
        return []
    matches = list(re.finditer(r'[^\s,;!?؟]+\.(?:md|txt)\b', text, re.I))
    out = matches[-1].group(0).strip(' \t,.;!?؟') if matches else 'file_organization_report.md'
    return [
        PlannedAction('s1', list_tool.capability, list_tool.tool, {'path': frame.slot('path') or '.'}, (), list_tool.effects,
                      'observe the workspace snapshot before changing any files'),
        PlannedAction('s2', organize_tool.capability, organize_tool.tool,
                      {'output_path': out}, ('s1',), organize_tool.effects,
                      'classify and move only the files present in the observed snapshot, then verify conservation and content fingerprints'),
        PlannedAction('s3', read_tool.capability, read_tool.tool, {'path': out}, ('s2',), read_tool.effects,
                      'reread the organization report so the final response is grounded in the persisted artifact'),
    ]


def _read_file(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    c = _pick_preferred(candidates, ('read_file', 'read_file_part'))
    if not c or not frame.slot('path'):
        return []
    return [PlannedAction('s1', c.capability, c.tool, {'path': frame.slot('path')}, (), c.effects,
                          'read the explicitly resolved local file rather than substituting a remote knowledge source')]

def _cross_department_data_move(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    recursive = _pick_preferred(candidates, ('list_files_recursive',))
    analyze = _pick_preferred(candidates, ('analyze_csv_collection',))
    move = _pick_preferred(candidates, ('move_workspace_file',))
    report = _pick_preferred(candidates, ('create_company_data_report',))
    read = _pick_preferred(candidates, ('read_file',))
    if not all((recursive, analyze, move, report, read)):
        return []
    import re
    text = str(getattr(frame, 'text', '') or '')
    matches = list(re.finditer(r'[^\s,;!?؟]+\.(?:md|txt)\b', text, re.I))
    out = matches[-1].group(0).strip(' \t,.;!?؟') if matches else 'company_data_report.md'
    if out.casefold().startswith('workspace/'):
        out = out.split('/', 1)[1]
    return [
        PlannedAction('s1', recursive.capability, recursive.tool, {'path': '.', 'exclude_path': out}, (), recursive.effects,
                      'observe the recursive workspace before analysis while excluding the report artifact from the source snapshot'),
        PlannedAction('s2', analyze.capability, analyze.tool, {'file_list': '{{s1}}', 'question': text}, ('s1',), analyze.effects,
                      'analyze every observed CSV and select the strongest candidate using deterministic totals'),
        PlannedAction('s3', move.capability, move.tool, {'destination_dir': 'processed_data'}, ('s2',), move.effects,
                      'execute the CEO handoff from Data to Operations using the selected file evidence'),
        PlannedAction('s4', report.capability, report.tool, {'analysis_result': '{{s2}}', 'move_result': '{{s3}}', 'output_path': out}, ('s2','s3'), report.effects,
                      'create the cross-department report from observed analysis and verified move evidence'),
        PlannedAction('s5', read.capability, read.tool, {'path': out}, ('s4',), read.effects,
                      'reread the final artifact for QA grounding'),
    ]


def _cross_department_sales_report_move(frame: Any, candidates: list[CandidateAction]) -> list[PlannedAction]:
    recursive = _pick_preferred(candidates, ('list_files_recursive',))
    analyze = _pick_preferred(candidates, ('analyze_csv_by_average',))
    report = _pick_preferred(candidates, ('create_sales_analysis_report',))
    move = _pick_preferred(candidates, ('move_workspace_report',))
    read = _pick_preferred(candidates, ('read_file',))
    if not all((recursive, analyze, report, move, read)):
        return []
    import re
    from pathlib import Path
    text = str(getattr(frame, 'text', '') or '')
    matches = list(re.finditer(r'[^\s,;!?؟]+\.(?:md|txt)\b', text, re.I))
    out = matches[-1].group(0).strip(' \t,.;!?؟') if matches else 'top_sales_analysis.md'
    if out.casefold().startswith('workspace/'):
        out = out.split('/', 1)[1]
    dest_match = re.search(r'(?:workspace[\\/])?([A-Za-z0-9_-]*selected[_-]reports[A-Za-z0-9_-]*)', text, re.I)
    destination_dir = dest_match.group(1) if dest_match else 'selected_reports'
    return [
        PlannedAction('s1', recursive.capability, recursive.tool,
                      {'path': '.', 'exclude_path': out}, (), recursive.effects,
                      'observe all CSV candidates from the current recursive workspace state before analysis', skill_key='builtin:workspace-recursive-inventory'),
        PlannedAction('s2', analyze.capability, analyze.tool,
                      {'file_list': '{{s1}}', 'question': text}, ('s1',), analyze.effects,
                      'rank CSV files by the requested sales/revenue average and retain source fingerprints', skill_key='builtin:data-analysis'),
        PlannedAction('s3', report.capability, report.tool,
                      {'analysis_result': '{{s2}}', 'output_path': out, 'destination_dir': destination_dir}, ('s2',), report.effects,
                      'create the selected-file analytical artifact from deterministic evidence', skill_key='builtin:data-analysis-report'),
        PlannedAction('s4', move.capability, move.tool,
                      {'source_path': out, 'destination_dir': destination_dir}, ('s3',), move.effects,
                      'handoff the completed report to Operations without overwriting and with content-integrity verification'),
        PlannedAction('s5', read.capability, read.tool,
                      {'path': '{{s4.destination}}'}, ('s4',), read.effects,
                      'reread the exact destination returned by the report move so QA can verify the persisted artifact'),
    ]


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
    Method('research_report', ('research_report',), 1.0, _research_report,
           'research, compare, and create a verified research artifact'),
    Method('project_audit', ('project_audit',), 1.0, _project_audit,
           'create a verified project audit from repository inspection and validation evidence'),
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
    Method('analyze_dataset_report', ('data_analysis_report',), 1.0, _data_analysis_report,
           'analyze a local dataset and create a verified report artifact'),
    Method('workspace_inventory', ('workspace_inventory',), 1.0, _workspace_inventory,
           'enumerate workspace files and create a verified inventory artifact'),
    Method('workspace_recursive_inventory', ('workspace_recursive_inventory',), 1.05, _workspace_recursive_inventory,
           'recursively inventory workspace folders, rank largest files, and verify the final artifact'),
    Method('file_read', ('file_read',), 1.0, _read_file,
           'read an explicitly resolved local file'),
    Method('workspace_file_organization', ('workspace_file_organization',), 1.0, _workspace_file_organization,
           'classify, move, and verify workspace files from one observed snapshot'),
    Method('workspace_duplicate_cleanup', ('workspace_duplicate_cleanup',), 1.05, _workspace_duplicate_cleanup,
           'detect duplicate content and safely archive redundant copies with verification'),
    Method('cross_department_data_move', ('cross_department_data_move',), 1.20, _cross_department_data_move,
           'route Data analysis to Operations movement and verify the handoff as one company workflow'),
    Method('cross_department_sales_report_move', ('cross_department_sales_report_move',), 1.22, _cross_department_sales_report_move,
           'rank sales files by average, create a verified report, move it through Operations, and verify the handoff'),
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

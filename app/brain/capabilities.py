from __future__ import annotations

from typing import Any

from app.brain.models import Capability, CandidateAction
from app.runtime.registry import Tool
import re


def _tokens(text: str) -> set[str]:
    value = re.sub(r"\s+", " ", str(text).casefold()).strip()
    return set(re.findall(r"[\w\u0600-\u06ff]+", value, flags=re.UNICODE))


def build_capabilities(registry: dict[str, Tool]) -> list[Capability]:
    result: list[Capability] = []
    for tool in registry.values():
        result.append(Capability(
            name=str(tool.capability or tool.name),
            tool=tool.name,
            description=tool.description,
            preconditions=tuple(tool.preconditions),
            effects=tuple(tool.produces),
            cost=float(tool.cost),
            risk=str(tool.risk),
            verification=str(tool.verification_level),
            reversible=not bool(tool.requires_approval),
        ))
    return sorted(result, key=lambda x: (x.name, x.tool))


def discover_candidates(frame: Any, registry: dict[str, Tool]) -> list[CandidateAction]:
    op = str(getattr(frame, 'requested_operation', '') or '')
    concepts = set(getattr(frame, 'concepts', ()) or ())
    slot_names = {k for k, _ in getattr(frame, 'slots', ()) or ()}
    candidates: list[CandidateAction] = []

    explicit = {
        'query_time': {'get_time', 'time'},
        'calculate': {'calculator', 'calculate'},
        'remember': {'remember_fact', 'remember_memory'},
        'forget_memory': {'forget_fact'},
        'query_identity': {'recall_fact', 'recall_last_result'},
        'query_memory': {'memory_search', 'memory_profile', 'recall_fact'},
        'research': {'research_memory_search', 'web_search', 'web_research', 'answer_question', 'agentic_rag', 'research', 'research_and_learn', 'internet_research', 'arxiv_research', 'github_search', 'github_research'},
        'learning_intent': {'research_and_learn', 'internet_research', 'web_research', 'agentic_rag'},
        'skill_query': {'list_skills', 'match_skills'},
        'compound_calculate_remember': {'calculator', 'calculate', 'remember_fact', 'remember_result'},
        'query_knowledge': {'answer_question', 'question_answering', 'agentic_rag'},
        'project_task': {'inspect_project', 'git_status', 'validate_project', 'build_project'},
        'development_inspection': {'inspect_project'},
        'file_read': {'read_file', 'read_file_part'},
        'development_validation': {'validate_project'},
        'data_analysis': {'profile_dataset', 'analyze_dataset'},
        'data_analysis_report': {'create_data_analysis_report'},
        'workspace_inventory': {'list_files', 'create_file_inventory', 'read_file'},
        'workspace_recursive_inventory': {'list_files_recursive', 'create_workspace_tree_inventory', 'read_file'},
        'workspace_file_organization': {'list_files', 'organize_workspace_files', 'move_workspace_report', 'read_file'},
        'workspace_duplicate_cleanup': {'list_files_recursive', 'deduplicate_workspace_files', 'read_file'},
        'cross_department_data_move': {'list_files_recursive', 'analyze_csv_collection', 'move_workspace_file', 'create_company_data_report', 'read_file'},
        'cross_department_sales_report_move': {'list_files_recursive', 'analyze_csv_by_average', 'create_sales_analysis_report', 'move_workspace_report', 'read_file'},
        'project_audit': {'create_project_audit_report', 'inspect_project', 'git_status', 'audit_project_tests'},
        'research_report': {'internet_research', 'arxiv_research', 'create_research_report'},
    }
    desired = explicit.get(op, set())
    for name, tool in registry.items():
        cap = str(tool.capability or name)
        score = 0.0
        reasons: list[str] = []
        if name in desired or cap in desired:
            score += 2.0; reasons.append('operation-capability')
        if any(c in cap.casefold() or c in name.casefold() for c in concepts):
            score += 0.45; reasons.append('concept')
        if op and (op == cap or op == name):
            score += 0.75; reasons.append('exact-operation')
        if score <= 0:
            continue
        params = tuple(str(k) for k in (tool.params or {}))
        missing = tuple(k for k in params if k not in slot_names)
        candidates.append(CandidateAction(
            capability=cap,
            tool=name,
            score=score,
            reason=','.join(reasons),
            requires_input=missing,
            reversible=not tool.requires_approval,
            preconditions=tuple(tool.preconditions),
            effects=tuple(tool.produces),
            risk=str(tool.risk),
            cost=float(tool.cost),
        ))
    candidates.sort(key=lambda x: (-x.score, x.cost, x.tool))
    return candidates[:10]


def discover_skill_candidates(goal_spec: Any, frame: Any, skill_bank: Any) -> list[Any]:
    """Discover executable Skills from capability requirements, not raw sentences."""
    if skill_bank is None:
        return []
    try:
        skills = skill_bank.list()
    except Exception:
        return []

    req_cap = str(getattr(goal_spec, 'required_capability', '') or '').casefold().strip()
    op = str(getattr(frame, 'requested_operation', '') or '').casefold().strip()
    target_caps = {x for x in (req_cap, op) if x}
    if not target_caps:
        return []

    matched: list[tuple[float, float, Any]] = []
    for skill in skills:
        if getattr(skill, 'status', '') not in {'approved', 'active'}:
            continue
        workflow = tuple(getattr(skill, 'workflow', ()) or ())
        workflow_caps: set[str] = set()
        workflow_tools: set[str] = set()
        for item in workflow:
            if not isinstance(item, dict):
                continue
            for key in ('capability', 'tool'):
                value = str(item.get(key, '') or '').casefold().strip()
                if value:
                    (workflow_caps if key == 'capability' else workflow_tools).add(value)
        declared = {
            str(getattr(skill, 'key', '') or '').casefold().strip(),
            str(getattr(skill, 'name', '') or '').casefold().strip(),
            *workflow_caps, *workflow_tools,
        }
        overlap = target_caps & declared
        trigger_tokens = set().union(*(_tokens(x) for x in (getattr(skill, 'triggers', ()) or ())))
        capability_tokens = _tokens(' '.join((*workflow_caps, *workflow_tools, *getattr(skill, 'outputs', ()))))
        trigger_fit = max((len(_tokens(cap)) and len(_tokens(cap) & trigger_tokens) / len(_tokens(cap)) for cap in target_caps), default=0.0)
        structural = 1.0 if overlap else 0.0
        if not overlap:
            # A trigger may support aliasing only when the target capability is explicit
            # in the Skill contract as a workflow capability/tool. Never select solely
            # because a user sentence contains a trigger phrase.
            continue
        score = float(getattr(skill, 'utility', 0.5)) + 0.55 * len(overlap) + 0.10 * trigger_fit
        matched.append((score, structural, skill))

    matched.sort(key=lambda x: (-x[0], -x[1], str(getattr(x[2], 'key', ''))))
    return [item[2] for item in matched]


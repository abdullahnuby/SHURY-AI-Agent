from __future__ import annotations

from typing import Any

from app.brain.models import Capability, CandidateAction
from app.runtime.registry import Tool


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

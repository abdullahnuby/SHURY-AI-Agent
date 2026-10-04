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


def discover_skill_candidates(goal_spec: Any, frame: Any, skill_bank: Any) -> list[Any]:
    """Discover and rank Skill candidates from SkillBank based on capability contracts.

    Skill selection depends on capability requirements, preconditions, and outputs,
    NOT on raw sentence-pattern matching.
    """
    if skill_bank is None:
        return []
    try:
        skills = skill_bank.list()
    except Exception:
        return []

    req_cap = str(getattr(goal_spec, 'required_capability', '') or getattr(goal_spec, 'name', '') or '').casefold().strip()
    op = str(getattr(frame, 'requested_operation', '') or '').casefold().strip()
    
    target_caps = set()
    if req_cap:
        target_caps.add(req_cap)
    if op:
        target_caps.add(op)

    matched = []
    for skill in skills:
        if getattr(skill, 'status', '') not in {'approved', 'active'}:
            continue
        
        skill_key = str(getattr(skill, 'key', '') or '').casefold().strip()
        skill_name = str(getattr(skill, 'name', '') or '').casefold().strip()
        triggers = tuple(str(x).casefold().strip() for x in (getattr(skill, 'triggers', ()) or ()))
        outputs = tuple(str(x).casefold().strip() for x in (getattr(skill, 'outputs', ()) or ()))
        
        skill_caps = {skill_key, skill_name}
        workflow = getattr(skill, 'workflow', ()) or ()
        for item in workflow:
            if isinstance(item, dict):
                cap = str(item.get('capability', '') or item.get('tool', '')).casefold().strip()
                if cap:
                    skill_caps.add(cap)
        
        skill_caps.update(triggers)
        skill_caps.update(outputs)

        # Require exact match on the target operation/capability or explicit trigger
        if not (target_caps & {skill_key, skill_name}) and not (req_cap and req_cap in skill_caps and req_cap in triggers):
            if not (op and op in skill_caps and (op == skill_key or op in triggers)):
                continue

        overlap = target_caps & skill_caps
        score = float(getattr(skill, 'utility', 0.5)) + len(overlap) * 0.5
        matched.append((score, skill))

    matched.sort(key=lambda x: (-x[0], str(getattr(x[1], 'key', ''))))
    return [item[1] for item in matched]


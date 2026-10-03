from __future__ import annotations

from app.brain.models import Decision, CognitiveState


def deliberate(state: CognitiveState) -> Decision:
    frame = state.semantic
    op = frame.requested_operation if frame else ''
    candidates = tuple(state.candidates[:8])

    # Social interaction is a cognitive state transition, not an action/tool call.
    if frame and frame.speech_act == 'greeting':
        return Decision('respond', 0.98, 'social greeting', answer_source='conversation', conclusion='greeting')

    if op == 'query_identity':
        evidence = tuple(state.evidence)
        if evidence:
            return Decision('respond', 0.98, 'identity query grounded in durable belief evidence', answer_source='memory',
                            evidence=evidence, conclusion=evidence[0].content)
        if frame and frame.slot('result:reference') == 'previous' and state.plan:
            step = state.plan[0]
            return Decision('execute', 0.98, 'previous result lookup is scoped to the active session',
                            capability=step.capability, tool=step.tool, candidates=candidates,
                            plan=tuple(state.plan), conclusion='session_result_lookup_required')
        return Decision('retrieve', 0.91, 'identity query requires durable belief lookup', answer_source='beliefs', query='name')

    if op == 'query_memory':
        if state.evidence:
            return Decision('respond', 0.94, 'memory query grounded in canonical memory evidence', answer_source='memory',
                            evidence=tuple(state.evidence[:8]), conclusion=state.evidence[0].content)
        return Decision('retrieve', 0.90, 'memory query requires belief retrieval', answer_source='beliefs', query=frame.text)

    if op == 'query_capabilities':
        return Decision('respond', 0.96, 'capability and self-model state are available', answer_source='self_model',
                        candidates=tuple(state.candidates[:8]), conclusion='self_model')

    # Unresolved discourse references are a real planning uncertainty. Do not execute
    # a plausible-looking action with the wrong referent.
    if frame and 'anaphoric_reference_unresolved' in frame.uncertainty:
        missing = ['anaphoric_reference_unresolved']
        if op == 'unknown_task' or 'capability_not_identified' in frame.uncertainty:
            missing.append('capability_not_identified')
        return Decision('clarify', 0.93, 'the requested object cannot be resolved from the current discourse state',
                        missing_information=tuple(dict.fromkeys(missing)))

    if op in {'query_time', 'calculate', 'remember', 'forget_memory', 'skill_query', 'compound_calculate_remember', 'data_analysis', 'project_task', 'development_inspection', 'development_validation'}:
        if state.plan:
            step = state.plan[0]
            return Decision('execute', 0.98, 'goal grounded into a deterministic action with a concrete contract',
                            capability=step.capability, tool=step.tool, candidates=candidates, plan=tuple(state.plan), conclusion='execution_required')
        return Decision('clarify', 0.82, 'a concrete action is intended but required inputs are incomplete',
                        missing_information=tuple(frame.uncertainty if frame else ()))

    if op in {'learning_intent', 'open_world_learning'}:
        topic = frame.slot('learning_topic') if frame else ''
        if topic:
            return Decision('research', 0.94, 'learning request converted into evidence-seeking research', answer_source='open_world_learning', query=topic, candidates=candidates, plan=tuple(state.plan), conclusion='learning_evidence_required')
        return Decision('clarify', 0.96, 'learning request has no topic to investigate', missing_information=('learning_topic',))

    if op in {'query_knowledge', 'research'}:
        query = frame.slot('query') if frame else state.user_text
        if state.evidence:
            return Decision('respond', 0.90, 'knowledge query resolved from existing local evidence',
                            answer_source='beliefs', evidence=tuple(state.evidence[:8]), query=query, conclusion=state.evidence[0].content)
        return Decision('research', 0.92, 'knowledge claims require explicit evidence before answering',
                        answer_source='rag_or_web', query=query, candidates=candidates, plan=tuple(state.plan), conclusion='evidence_required')

    if frame and frame.uncertainty:
        return Decision('clarify', 0.78, 'uncertainty affects the executable goal or source selection',
                        missing_information=tuple(frame.uncertainty))

    return Decision('clarify', 0.46, 'no grounded goal/capability pair exists yet',
                    missing_information=('goal_or_capability',))

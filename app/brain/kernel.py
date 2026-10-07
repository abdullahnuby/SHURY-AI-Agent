from __future__ import annotations

import os
import json
import math
import time
import uuid
import copy
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any, Callable

from app.brain.capabilities import build_capabilities, discover_candidates, discover_skill_candidates
from app.skills.registry import SkillBank
from app.brain.deliberation import deliberate
from app.brain.inference import infer, rank_beliefs
from app.brain.self_model import SelfModel
from app.brain.models import ActionSpec, Belief, CognitiveState, Decision, Evidence, GoalSpec, PlannedAction, SemanticFrame
from app.brain.perception import perceive
from app.brain.planner import make_goal, plan, replan
from app.brain.response import compose, compose_action_result
from app.brain.store import BrainStateStore
from app.knowledge.memory import get_memory
from app.knowledge.memory_controller import MemoryController
from app.learning.manager import SelfImprovementManager
from app.learning.store import LearningStore
from app.domain.plan import Plan, PlanStep
from app.runtime.registry import Tool, load_tools
from app.runtime.policy import check_tool
from app.runtime.verify import verify_step
from app.skills.verification import verify_skill_contract
from app.brain.structured import validate_structured_goal
from app.intelligence.semantic import semantic_understand
from app.organization import DEFAULT_COMPANY
from app.runtime.memory_context import push_memory, pop_memory
from app.organization import review_company_execution, CompanyMemory, CompanyGovernance, GovernanceContext
from app.organization.evidence import CompanyEvidencePolicy
from app.organization.scheduler import CompanyScheduler
from app.organization.context import (
    CompanyContextViolation, assert_references_allowed, company_context,
)


@dataclass(frozen=True)
class BrainResult:
    state: CognitiveState
    response: str = ''
    runtime_state: Any = None
    status: str = 'completed'
    run_id: str = ''


class CognitiveKernel:
    """V23 cognitive system.

    This is intentionally independent from legacy generative runtimes. It operates on semantic
    frames, persistent beliefs, goals, capability
    contracts, deterministic actions, observations and verified experience.
    """

    def __init__(self, *, memory=None, registry: dict[str, Tool] | None = None,
                 state_store: BrainStateStore | None = None,
                 experience_store: LearningStore | None = None,
                 learning_manager: SelfImprovementManager | None = None,
                 skill_bank: SkillBank | None = None):
        self.memory = memory or get_memory()
        self.memory_controller = MemoryController(self.memory)
        self.registry = registry or load_tools()
        self.state_store = state_store or BrainStateStore()
        self.skill_bank = skill_bank or SkillBank()
        learning_store = None
        if isinstance(experience_store, LearningStore):
            learning_store = experience_store
        elif experience_store is not None:
            learning_store = getattr(experience_store, 'store', None)
        self.learning = learning_manager or SelfImprovementManager(store=learning_store)
        self.experiences = self.learning.store
        self.self_model = SelfModel(self.registry, self.experiences)
        self.company = DEFAULT_COMPANY
        self.company_memory = CompanyMemory(self.memory)
        self.company_evidence = CompanyEvidencePolicy()

    def _load_beliefs(self, session_id: str) -> list[Belief]:
        """Return a Brain-safe projection supplied by the canonical Memory Controller."""
        try:
            bundle = self.memory_controller.profile_evidence(session_id=session_id)
        except Exception:
            bundle = None
        if bundle is None:
            return []
        result: list[Belief] = []
        for item in bundle.evidence:
            if item.memory_type not in {"fact", "preference", "note"}:
                continue
            content = item.content
            predicate, _, value = content.partition(" = ")
            if not predicate or not value:
                continue
            result.append(Belief(
                subject="user", predicate=predicate, value=value,
                confidence=float(item.confidence), source="canonical_memory", provenance=item.provenance or "memory-controller",
                created_at="", updated_at="", revision=1, status="active", supersedes="",
            ))
        return result

    def _sync_legacy_fact(self, session_id: str, predicate: str) -> Any:
        """Compatibility name for projecting a canonical Memory fact into Brain state.

        The read authority is always `Memory`; `BrainStateStore` receives only a derived copy.
        """
        try:
            key = self.memory.canonical_key(predicate)
            value = self.memory.get_fact(key, session_id=session_id)
        except Exception:
            value = None
            key = str(predicate or '')
        if value is not None and session_id:
            try:
                self.state_store.upsert_belief(
                    session_id=session_id, subject='user', predicate=key, value=value,
                    confidence=1.0, source='canonical_memory', provenance='memory-projection',
                )
            except Exception:
                pass
        return value

    def _remember_belief(self, session_id: str, predicate: str, value: Any, *, provenance: str = 'user_statement') -> Belief:
        """Write durable user memory through the single canonical Memory authority.

        The Brain belief row is a derived projection retained for compatibility and
        reasoning snapshots; it never decides the durable value.
        """
        key = self.memory.canonical_key(predicate)
        previous_value = self.memory.get_fact(key)
        self.memory.set_fact(key, value)
        canonical_value = self.memory.get_fact(key)
        row = self.state_store.upsert_belief(
            session_id=session_id, subject='user', predicate=key, value=canonical_value,
            confidence=1.0, source='canonical_memory', provenance='memory-projection',
        )
        if previous_value is not None and previous_value != canonical_value:
            self.state_store.append_event(session_id, 'belief_revision', {
                'subject': 'user', 'predicate': key, 'previous_value': previous_value,
                'new_value': canonical_value, 'revision': int(row['revision']), 'supersedes': row.get('supersedes', ''),
            })
        return Belief(
            subject='user', predicate=key, value=canonical_value, confidence=1.0, source='canonical_memory',
            provenance=provenance, revision=int(row['revision']), status='active',
            updated_at=str(row.get('updated_at') or ''), supersedes=str(row.get('supersedes', '')),
        )

    def perceive(self, user_text: str, *, session_id: str) -> CognitiveState:
        events = self.state_store.recent_events(session_id, limit=20)
        last_goal = ''
        recent_topics: list[str] = []
        # recent_events() is newest-first. The first goal_formed event is therefore
        # the active previous goal for the current turn; scanning in reverse would
        # incorrectly resurrect an older topic after a topic switch.
        for event in events:
            if event['kind'] == 'goal_formed' and not last_goal:
                last_goal = str(event['payload'].get('objective') or '')
            topic = str(event['payload'].get('topic') or '')
            if topic:
                recent_topics.append(topic)

        # Keep the legacy Brain perception as a deterministic fallback, but make the
        # retrieval-native Arabic NLP layer the primary semantic source for natural chat.
        # This is the critical bridge: previously `run_brain()` never consumed the
        # Arabic-Retrieval semantic parse, so statements such as "أنا من الأقصر"
        # arrived at the Brain as a generic `statement` and were forced into clarification.
        fallback_frame = perceive(user_text, last_goal=last_goal, recent_topics=tuple(recent_topics[-8:]))
        frame = fallback_frame
        try:
            semantic_world = SimpleNamespace(
                last_goal=last_goal,
                last_outputs={},
            )
            parsed = semantic_understand(
                user_text,
                mem=self.memory,
                world=semantic_world,
                registry=self.registry,
                session_id=session_id,
            )
            parsed_slots = dict(parsed.slots)

            # Normalize Layer-2 memory namespaces into the Brain's stable slot contract.
            if parsed_slots.get('recall:key') is not None:
                parsed_slots.setdefault('key', parsed_slots['recall:key'])
            if parsed_slots.get('forget:key') is not None:
                parsed_slots.setdefault('key', parsed_slots['forget:key'])
            if parsed_slots.get('operation:expression') is not None:
                parsed_slots.setdefault('expression', parsed_slots['operation:expression'])
            if parsed_slots.get('result:key') is not None:
                parsed_slots.setdefault('result_key', parsed_slots['result:key'])
            if parsed_slots.get('research:query') is not None:
                parsed_slots.setdefault('query', parsed_slots['research:query'])
            if parsed_slots.get('memory:query') is not None:
                parsed_slots.setdefault('query', parsed_slots['memory:query'])
            if parsed_slots.get('learning_topic') is not None:
                parsed_slots.setdefault('query', parsed_slots['learning_topic'])
            if parsed_slots.get('fact:name') is not None:
                parsed_slots.setdefault('predicate', 'name')
                parsed_slots.setdefault('value', parsed_slots['fact:name'])
            if parsed_slots.get('fact:city') is not None:
                parsed_slots.setdefault('predicate', 'city')
                parsed_slots.setdefault('value', parsed_slots['fact:city'])
            if parsed_slots.get('fact:origin') is not None:
                parsed_slots.setdefault('predicate', 'origin')
                parsed_slots.setdefault('value', parsed_slots['fact:origin'])
            if parsed_slots.get('fact:job') is not None:
                parsed_slots.setdefault('predicate', 'job')
                parsed_slots.setdefault('value', parsed_slots['fact:job'])
            if parsed_slots.get('fact:preference') is not None:
                parsed_slots.setdefault('predicate', 'preference')
                parsed_slots.setdefault('value', parsed_slots['fact:preference'])
            # Generic explicit facts use their natural user-supplied key as predicate.
            # Project this arbitrary fact slot into the canonical remember tool contract so
            # memory phrases such as "خزّن كود الفرع: EGY-7" do not become planner ambiguity.
            if not parsed_slots.get('predicate') or not parsed_slots.get('value'):
                generic_facts = [(str(k)[5:], str(v)) for k, v in parsed_slots.items() if str(k).startswith('fact:') and str(k)[5:]]
                if generic_facts:
                    predicate, value = generic_facts[0]
                    parsed_slots.setdefault('predicate', predicate)
                    parsed_slots.setdefault('value', value)

            top_intent = parsed.intent_candidates[0].name if parsed.intent_candidates else ''
            operation = str(top_intent or fallback_frame.requested_operation or '').strip()
            if getattr(parsed, 'needs_clarification', False):
                fallback_operation = str(fallback_frame.requested_operation or '').strip()
                operation = fallback_operation if fallback_operation not in {'', 'statement'} else 'unknown_task'
            if operation == 'recall_fact':
                operation = 'query_identity' if parsed_slots.get('key', '') == 'name' else 'query_memory'
            elif operation in {'memory_search', 'memory_profile', 'memory_stats'}:
                operation = 'query_memory'
            elif operation == 'knowledge_query':
                operation = 'query_knowledge'
            elif operation == 'open_world_learning':
                external_markers = (
                    'from web', 'from the web', 'from internet', 'from the internet',
                    'search online', 'search the internet', 'on the web', 'on the internet',
                    'الويب', 'الإنترنت', 'الانترنت', 'اونلاين', 'أونلاين',
                )
                # `research` is the canonical Brain operation for explicit external
                # evidence. Internal/open-ended learning remains `learning_intent`;
                # the semantic intent can remain open_world_learning for capability data.
                operation = 'research' if any(marker in parsed.normalized for marker in external_markers) else 'learning_intent'
            elif parsed_slots.get('expression') and (parsed_slots.get('result:key') or parsed_slots.get('result_key')):
                operation = 'compound_calculate_remember'
            elif operation in {'remember_fact', 'remember_memory'}:
                operation = 'remember'
            elif operation == 'forget_fact':
                operation = 'forget_memory'

            # Only replace the fallback operation when the semantic layer found a concrete
            # operation. Otherwise preserve the mature deterministic Brain parser.
            use_parsed_frame = bool(
                operation and operation not in {'statement', 'unknown_task'}
            ) or bool(getattr(parsed, 'references', None)) or bool(getattr(parsed, 'needs_clarification', False)) or bool(parsed_slots)
            if use_parsed_frame:
                frame = SemanticFrame(
                    text=parsed.original,
                    language=parsed.language,
                    speech_act=parsed.speech_act,
                    concepts=tuple(sorted((set(parsed_slots.keys()) | {str(top_intent)}) - {''})),
                    entities=tuple((item.text, item.type) for item in parsed.entities),
                    requested_operation=operation,
                    object_text=str(getattr(parsed, 'canonical_goal', '') or parsed.original),
                    slots=tuple(sorted((str(k), str(v)) for k, v in parsed_slots.items())),
                    question_type=('memory_fact' if operation in {'remember', 'remember_fact'} else ''),
                    temporal=tuple(str(x) for x in parsed.temporal),
                    conditions=tuple(f'{c.key}:{c.operator}:{c.value}' for c in parsed.constraints),
                    uncertainty=tuple(dict.fromkeys(
                        [str(x) for x in (parsed.required_information or ())] +
                        [str(x) for x in (parsed.ambiguity_reasons or ())] +
                        [
                            str(x) for x in (parsed.safety_signals or ())
                            if str(x) in {
                                'workspace_reference_outside_boundary',
                                'workspace_destination_outside_boundary',
                            }
                        ]
                    )),
                    memory_need=getattr(parsed, 'memory_need', 'none'),
                    memory_types=tuple(getattr(parsed, 'memory_types', ()) or ()),
                    memory_reason=str(getattr(parsed, 'memory_reason', '') or ''),
                )
                # Declarative user facts are not ambiguous goals. The semantic parser has
                # already grounded them into a concrete memory operation + predicate/value.
                if operation == 'remember' and frame.slot('predicate') and frame.slot('value') and not getattr(parsed, 'needs_clarification', False):
                    frame = SemanticFrame(
                        text=frame.text, language=frame.language, speech_act='statement',
                        concepts=tuple(sorted(set(frame.concepts) | {'memory'})),
                        entities=frame.entities, requested_operation='remember',
                        object_text=frame.object_text, slots=frame.slots,
                        question_type=frame.question_type, temporal=frame.temporal,
                        conditions=frame.conditions, uncertainty=(),
                        memory_need=frame.memory_need, memory_types=frame.memory_types, memory_reason=frame.memory_reason,
                    )
        except Exception:
            # Required/strict production mode must fail closed when the canonical semantic
            # dependency cannot execute. Optional/off modes retain the deterministic legacy
            # fallback for offline tests and compatibility paths.
            mode = os.getenv("SHURY_NLP_MODE", "required").strip().casefold()
            if mode in {"required", "strict"}:
                raise
            frame = fallback_frame

        state = CognitiveState(user_text=user_text, session_id=session_id, semantic=frame, revision=len(events))
        state.beliefs = self._load_beliefs(session_id)
        state.event('perception', speech_act=frame.speech_act, operation=frame.requested_operation,
                    concepts=list(frame.concepts), uncertainty=list(frame.uncertainty))
        return state

    def retrieve(self, state: CognitiveState) -> None:
        frame = state.semantic
        if frame is None:
            return

        bundle = None
        if getattr(frame, 'memory_need', 'none') != 'none':
            try:
                bundle = self.memory_controller.retrieve_for_frame(
                    frame, session_id=state.session_id, run_id=getattr(state, "run_id", None), limit=8
                )
                state.evidence = bundle.to_brain_evidence()
            except Exception as exc:
                state.event('memory_controller_error', error=f'{type(exc).__name__}: {exc}')
                state.evidence = []
                bundle = None
            state.event(
                'memory_requirement',
                need=frame.memory_need,
                memory_types=list(frame.memory_types),
                selected_stores=list(bundle.selected_stores) if bundle else [],
                evidence_count=bundle.count if bundle else 0,
                rationale=frame.memory_reason,
            )

        if frame.requested_operation in {'query_identity', 'query_memory'} and not state.evidence:
            try:
                bundle = self.memory_controller.retrieve_for_frame(
                    frame, session_id=state.session_id, run_id=getattr(state, "run_id", None), limit=8
                )
                state.evidence = bundle.to_brain_evidence()
            except Exception as exc:
                state.event('memory_controller_error', error=f'{type(exc).__name__}: {exc}')
                state.evidence = []
            if state.evidence:
                state.beliefs = self._load_beliefs(state.session_id or '')

        if frame.requested_operation == 'query_knowledge':
            query = frame.slot('query') or frame.text
            state.event('evidence_requirement', source='knowledge_memory_or_external', query=query, local_hits=len(state.evidence))
        elif frame.requested_operation == 'query_capabilities':
            state.event('evidence_requirement', source='capability_registry')
        state.event('retrieval', evidence_count=len(state.evidence))

    def _persist_new_statement(self, state: CognitiveState) -> None:
        frame = state.semantic
        if frame is None or frame.requested_operation != 'remember':
            return
        predicate = frame.slot('predicate')
        value = frame.slot('value')
        if predicate and value:
            belief = self._remember_belief(state.session_id or '', predicate, value)
            state.beliefs = self._load_beliefs(state.session_id or '')
            state.evidence = [Evidence('belief', f'{predicate} = {value}', 'user', 1.0,
                                        f'user:{predicate}:r{belief.revision}', belief.provenance)]
            state.event('belief_update', predicate=predicate, revision=belief.revision)

    def _plan_state(self, state: CognitiveState, *, goal_override: GoalSpec | None = None) -> CognitiveState:
        state.capabilities = build_capabilities(self.registry)
        state.self_model = self.self_model.snapshot()
        state.candidates = discover_candidates(state.semantic, self.registry) if state.semantic else []
        state.action_specs = [ActionSpec.from_candidate(candidate) for candidate in state.candidates]
        state.hypotheses = infer(state)
        state.goal = goal_override or (make_goal(state.semantic) if state.semantic else GoalSpec('open_task', state.user_text))
        state.company_project_id = str(getattr(state.goal, 'project_id', '') or '')
        state.company_project_context = {}
        state.company_portfolio = {}
        if state.company_project_id:
            try:
                project = self.company.portfolio.get_project(state.company_project_id)
                if project is None:
                    raise ValueError(f'unknown company project: {state.company_project_id}')
                state.company_project_context = project.to_dict()
                state.company_portfolio = self.company.portfolio.snapshot()
                state.event('company_project_bound', project=state.company_project_context)
            except Exception as exc:
                state.event('company_project_binding_failed', project_id=state.company_project_id, error=f'{type(exc).__name__}: {exc}')
                raise
        else:
            state.company_portfolio = self.company.portfolio.snapshot()
        state.event('goal_formed', objective=state.goal.objective, name=state.goal.name, query=state.goal.query,
                    project_id=state.company_project_id, horizon=getattr(state.goal, 'horizon', 'medium'))
        self.state_store.append_event(state.session_id or '', 'goal_formed', {
            'topic': state.goal.name, 'objective': state.goal.objective, 'query': state.goal.query,
            'source': 'structured_goal' if goal_override else 'natural_language',
        })
        state.beliefs = self._load_beliefs(state.session_id or '')

        # C10: retrieve only durable, verified organizational memory. This lane is separate
        # from user/session/run memory and is injected as evidence, never as task state.
        try:
            company_hits = self.company_memory.recall_for_goal(state.goal.objective if state.goal else state.user_text, top_k=6, project_id=state.company_project_id or None)
            state.company_memory = [hit.to_dict() for hit in company_hits]
            state.event('company_memory_retrieved', count=len(company_hits), hits=state.company_memory)
        except Exception as exc:
            state.company_memory = []
            state.event('company_memory_retrieval_error', error=f'{type(exc).__name__}: {exc}')
        
        # Micro-Phase 2: Skill Selection as a First-Class Brain Decision
        # Skill matching depends on capability requirements and Skill contracts from SkillBank.
        state.selected_skills = discover_skill_candidates(state.goal, state.semantic, self.skill_bank) if state.semantic else []
        state.selected_skill = state.selected_skills[0] if state.selected_skills else None
        if state.selected_skill:
            state.event('skill_selected', key=getattr(state.selected_skill, 'key', ''), name=getattr(state.selected_skill, 'name', ''))

        selected_skill_key = str(getattr(state.selected_skill, 'key', '') or '')

        if state.semantic and state.semantic.requested_operation in {'query_identity', 'query_memory'} and not state.evidence:
            query = state.semantic.slot('query') or state.goal.query or 'name'
            state.evidence = rank_beliefs([b.to_dict() for b in state.beliefs], query, limit=8)
        state.plan = plan(
            state.goal, state.semantic, state.candidates,
            state=state, experiences=self.experiences,
            learning=self.learning, registry=self.registry,
            # Structured GoalSpec requests already carry an explicit operation/capability.
            # Do not let exploratory learning replace that typed workflow before execution.
            allow_exploration=goal_override is None,
        ) if state.semantic else []

        # A selected Skill is only authoritative when the materialized plan actually carries
        # that Skill's contract. A failed Skill expansion must not leave a stale Skill attached
        # to a different deterministic plan and invalidate an otherwise verified execution.
        if state.selected_skill is not None:
            selected_key = str(getattr(state.selected_skill, 'key', '') or '')
            bound_keys = {str(getattr(step, 'skill_key', '') or '') for step in state.plan}
            if selected_key and selected_key not in bound_keys:
                state.event('skill_selection_unbound', selected_skill=selected_key, plan_skill_keys=sorted(x for x in bound_keys if x))
                state.selected_skill = None
                state.selected_skills = []

        # Company Phase 5: the CEO first synthesizes the required capabilities from the
        # structured semantic/task state. This is intentionally separate from routing so a
        # novel capability can be resolved without introducing a workflow-name mapping.
        capability_plan = None
        task_ir = None
        if state.semantic:
            try:
                from app.intelligence.task_compiler import compile_task_ir
                task_ir = compile_task_ir(state.semantic)
            except Exception as exc:
                state.event('company_capability_synthesis_error', error=f'{type(exc).__name__}: {exc}')
            capability_plan = self.company.registry.synthesize_capabilities(
                semantic=state.semantic, task_ir=task_ir, plan=state.plan, tool_registry=self.registry
            )
            state.company_capability_plan = capability_plan.to_dict()
            state.event('company_capability_synthesis', **state.company_capability_plan)

            # Bounded novelty bridge: only synthesize a new executable plan when the normal
            # planner produced none, TaskIR is executable, and every required capability has
            # an exact declared tool owner. No fuzzy sentence-to-tool execution is allowed.
            if not state.plan and task_ir is not None and bool(getattr(task_ir, 'executable', False)):
                try:
                    synthesized_plan, synthesized_capabilities = self.company.registry.synthesize_executable_plan(
                        semantic=state.semantic, task_ir=task_ir, tool_registry=self.registry
                    )
                    if synthesized_plan:
                        state.plan = synthesized_plan
                        state.company_capability_plan = synthesized_capabilities.to_dict()
                        state.event('company_capability_plan_synthesized',
                                    plan=[x.to_dict() for x in state.plan],
                                    capability_plan=state.company_capability_plan)
                except Exception as exc:
                    state.event('company_capability_plan_synthesis_error', error=f'{type(exc).__name__}: {exc}')

        state.event('planning', plan=[x.to_dict() for x in state.plan])
        assignments = self.company.route_plan(
            state.goal.objective if state.goal else state.user_text, state.plan, tool_registry=self.registry,
            project_id=str(getattr(state, 'company_project_id', '') or ''),
            horizon=str(getattr(state.goal, 'horizon', 'medium') if state.goal else 'medium'),
        )
        state.company_assignments = [{**a.to_dict(), 'mandate': self.company.mandate(a, str(getattr(state.plan[i], 'skill_key', '') or '')).to_dict() if str(getattr(state.plan[i], 'skill_key', '') or '') else {}} for i, a in enumerate(assignments)]
        state.company_coordination = self.company.coordinate(
            state.goal.objective if state.goal else state.user_text, assignments, tool_registry=self.registry
        ).to_dict()
        if state.company_project_id:
            try:
                synced = self.company.portfolio.sync_coordination(state.company_project_id, state.company_coordination)
                state.event('company_project_tasks_synced', project_id=state.company_project_id, task_count=len(synced))
                state.company_portfolio = self.company.portfolio.snapshot()
            except Exception as exc:
                state.event('company_project_task_sync_error', project_id=state.company_project_id, error=f'{type(exc).__name__}: {exc}')
                raise
        state.event('company_executive_decomposition',
                    workstreams=state.company_coordination.get('workstreams', []),
                    execution_waves=state.company_coordination.get('execution_waves', []),
                    handoffs=state.company_coordination.get('handoffs', []),
                    critical_path=state.company_coordination.get('critical_path', []),
                    required_capabilities=state.company_coordination.get('required_capabilities', []),
                    unresolved_capabilities=state.company_coordination.get('unresolved_capabilities', []),
                    validation_errors=state.company_coordination.get('validation_errors', []),
                    team_formation=state.company_coordination.get('team_formation', {}))
        if state.company_assignments:
            state.company_assignment = dict(state.company_assignments[0])
            state.event('company_workflow_delegation', assignments=state.company_assignments)
            state.event('company_coordination', coordination=state.company_coordination)
            for item in state.company_assignments:
                state.event('company_delegation', **item)
        canonical = state.to_canonical_state()
        state.event('canonical_state', fingerprint=canonical.fingerprint(),
                    pending_actions=list(canonical.pending_actions), completed_actions=list(canonical.completed_actions),
                    failure_count=len(canonical.failures), uncertainty=list(canonical.uncertainty))
        state.decision = deliberate(state)
        state.event('decision', decision_kind=state.decision.kind, confidence=state.decision.confidence,
                    rationale=state.decision.rationale)
        return state

    def think(self, user_text: str, *, session_id: str | None = None) -> BrainResult:
        sid = session_id or uuid.uuid4().hex
        state = self.perceive(user_text, session_id=sid)
        if state.semantic and state.semantic.uncertainty:
            decision = deliberate(state)
            if decision.kind == 'clarify':
                state.decision = decision
                state.event('decision', decision_kind=decision.kind, confidence=decision.confidence,
                            rationale=decision.rationale)
                response = compose(decision, state)
                self.state_store.append_event(sid, 'turn_decided', {
                    'topic': '', 'objective': user_text,
                    'decision': decision.kind, 'tool': '',
                })
                return BrainResult(state, response, status='decided', run_id=uuid.uuid4().hex)
        self.retrieve(state)
        self._plan_state(state)
        response = compose(state.decision, state)
        self.state_store.append_event(sid, 'turn_decided', {
            'topic': state.goal.name if state.goal else '', 'objective': user_text,
            'decision': state.decision.kind if state.decision else '',
            'tool': state.decision.tool if state.decision else '',
        })
        return BrainResult(state, response, status='decided', run_id=uuid.uuid4().hex)

    def think_structured(self, payload: dict[str, Any] | GoalSpec, *, session_id: str | None = None) -> BrainResult:
        if isinstance(payload, GoalSpec):
            goal = payload
            frame = SemanticFrame(
                text=goal.objective, language='en', speech_act='command',
                concepts=tuple(sorted({goal.name})), requested_operation=goal.name,
                slots=tuple(sorted((('query', goal.query),) if goal.query else ())),
                uncertainty=(),
            )
            metadata = {'source': 'structured_goal', 'target': '', 'capability': goal.name, 'parameters': {}, 'slots': dict(frame.slots)}
        else:
            goal, frame, metadata = validate_structured_goal(payload)
        sid = session_id or uuid.uuid4().hex
        events = self.state_store.recent_events(sid, limit=20)
        state = CognitiveState(user_text=goal.objective, session_id=sid, semantic=frame, revision=len(events))
        state.beliefs = self._load_beliefs(sid)
        state.event('structured_goal_received', **metadata)
        self.retrieve(state)
        self._plan_state(state, goal_override=goal)
        state.event('structured_mode', semantic_model='arabic-retrieval-v1.0')
        response = compose(state.decision, state)
        return BrainResult(state, response, status='decided', run_id=uuid.uuid4().hex)

    def _resolve_action_args(self, action: PlannedAction, outputs: dict[str, Any], *,
                             allowed_dependencies: set[str] | None = None) -> dict[str, Any]:
        """Resolve only explicit dependency references; never expose unrelated prior outputs."""
        allowed = set(allowed_dependencies if allowed_dependencies is not None else action.depends_on or ())

        def resolve_reference(token: str) -> Any:
            import re
            match = re.fullmatch(r"\{\{(s\d+)(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[([A-Za-z_][A-Za-z0-9_]*)\])?\}\}", token)
            if not match:
                return None, False
            step_id, field, bracket_field = match.groups()
            if step_id not in allowed:
                raise CompanyContextViolation(
                    f"step {action.step_id} references undeclared dependency {step_id}"
                )
            if step_id not in outputs:
                return None, False
            value = outputs[step_id]
            key = field or bracket_field
            if key is None:
                return value, True
            if isinstance(value, dict) and key in value:
                return value[key], True
            return None, False

        def resolve(value: Any) -> Any:
            if isinstance(value, str):
                exact, ok = resolve_reference(value)
                if ok:
                    return exact
                import re
                refs = tuple(m.group(1) for m in re.finditer(r"\{\{(s\d+)\}\}", value))
                for step_id in refs:
                    if step_id not in allowed:
                        raise CompanyContextViolation(
                            f"step {action.step_id} references undeclared dependency {step_id}"
                        )
                    if step_id in outputs:
                        value = value.replace('{{' + step_id + '}}', str(outputs[step_id]))
                return value
            if isinstance(value, dict):
                return {k: resolve(v) for k, v in value.items()}
            if isinstance(value, list):
                return [resolve(v) for v in value]
            return value

        args = resolve(dict(action.args or {}))
        tool = self.registry.get(action.tool)
        pipe_param = getattr(tool, 'pipe_param', None) if tool is not None else None
        if pipe_param and (pipe_param not in args or args.get(pipe_param) in (None, "")):
            for dep in reversed(tuple(action.depends_on or ())):
                if dep in allowed and dep in outputs:
                    args[pipe_param] = outputs[dep]
                    break
        return args

    @staticmethod
    def _goal_action_requirements(goal: str) -> dict[str, bool]:
        import re
        text = str(goal or '').casefold()
        return {
            'move': bool(re.search(r"(?:انقل|حرك|حرّك|نقل|move|transfer|put)\b", text, re.I)),
            'copy': bool(re.search(r"(?:انسخ|نسخ|copy)\b", text, re.I)),
            'report': bool(re.search(r"(?:تقرير|report)\b", text, re.I)),
        }

    def _validate_action_coverage(self, state: CognitiveState, action: PlannedAction, args: dict[str, Any]) -> tuple[bool, str]:
        requirements = self._goal_action_requirements(state.user_text)
        tool = self.registry.get(action.tool)
        if tool is None:
            return False, 'الأداة المطلوبة غير متاحة.'
        if requirements['move']:
            if 'move' not in action.tool.casefold() and 'move' not in str(action.capability).casefold():
                return False, 'الأداة المختارة لا تغطي فعل نقل الملف المطلوب.'
            if not str(args.get('source_path') or args.get('analysis_result') or '').strip():
                return False, 'مسار الملف المصدر غير محدد.'
            if not str(args.get('destination_dir') or '').strip():
                return False, 'مجلد الوجهة غير محدد.'
        destination = ''
        if state.semantic is not None:
            destination = str(state.semantic.slot('destination_dir') or '').strip()
        if destination and 'destination_dir' in (tool.params or {}):
            actual = str(args.get('destination_dir') or '').strip().replace('\\', '/')
            expected = destination.replace('\\', '/')
            if actual.casefold() != expected.casefold():
                return False, 'الوجهة في الخطة لا تطابق الوجهة التي حددها المستخدم.'
        return True, ''

    @staticmethod
    def _filesystem_goal_postcondition(state: CognitiveState, action: PlannedAction, output: Any) -> tuple[bool, str]:
        import re
        from pathlib import Path
        from app.runtime.security import safe_workspace_path
        goal = str(state.user_text or '').casefold()
        requirements = CognitiveKernel._goal_action_requirements(goal)
        if requirements['move']:
            if not isinstance(output, dict):
                return False, 'نتيجة النقل غير منظمة بما يكفي للتحقق منها.'
            if any(key in output and int(output.get(key) or 0) == 0 for key in ('moved_file_count', 'results_count')):
                return False, 'لم يتم نقل أي ملف رغم أن الهدف طلب نقل ملف.'
            source = str(output.get('source') or '').strip()
            destination = str(output.get('destination') or '').strip()
            if not source or not destination:
                return False, 'نتيجة النقل لا تحتوي المصدر والوجهة للتحقق.'
            try:
                source_path = safe_workspace_path(source)
                destination_path = safe_workspace_path(destination)
            except Exception:
                return False, 'تعذر التحقق من مسارات النقل داخل workspace.'
            if source_path.exists() or not destination_path.is_file():
                return False, 'التحقق النهائي للنقل فشل: المصدر أو الوجهة لا يطابقان الحالة المطلوبة.'
            if output.get('source_removed') is False:
                return False, 'ملف المصدر ما زال موجودًا بعد النقل.'
            return True, ''

        if not isinstance(output, dict):
            return True, ''
        operation = str(getattr(state.semantic, 'requested_operation', '') or '') if state.semantic else ''
        if requirements['report']:
            path_value = str(output.get('path') or '').strip()
            if not path_value:
                return False, 'نتيجة التقرير لا تحتوي مسار الملف الناتج.'
            try:
                report_path = safe_workspace_path(path_value)
            except Exception:
                return False, 'مسار التقرير خرج عن حدود workspace.'
            if not report_path.is_file() or report_path.stat().st_size == 0:
                return False, 'ملف التقرير غير موجود أو فارغ.'
            if output.get('verified') is False or (isinstance(output.get('goal_verification'), dict) and output['goal_verification'].get('ok') is False):
                return False, 'محتوى التقرير لم يمرّ بوابة التحقق الخاصة بالهدف.'
        return True, ''
    @staticmethod
    def _bounded_tool_run(tool: Tool, args: dict[str, Any], timeout_seconds: float | None):
        if timeout_seconds is None or timeout_seconds <= 0:
            return tool.run(**args)
        result_queue: queue.Queue[Any] = queue.Queue(maxsize=1)
        def worker() -> None:
            try:
                result_queue.put(tool.run(**args), timeout=0.1)
            except Exception as exc:
                result_queue.put(type('TimedResult', (), {'ok': False, 'data': None, 'error': f'{type(exc).__name__}: {exc}'})())
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            return result_queue.get(timeout=max(0.001, float(timeout_seconds)))
        except queue.Empty:
            return type('TimedResult', (), {'ok': False, 'data': None, 'error': 'execution timeout'})()

    @staticmethod
    def _bounded_call(fn: Callable[[], Any], timeout_seconds: float | None) -> tuple[bool, Any, str | None]:
        """Run a potentially blocking cognitive stage without allowing the caller to wait past its budget."""
        if timeout_seconds is None:
            try:
                return True, fn(), None
            except Exception as exc:
                return False, None, f'{type(exc).__name__}: {exc}'
        if timeout_seconds <= 0:
            return False, None, 'execution timeout'
        result_queue: queue.Queue[Any] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                result_queue.put((True, fn(), None), timeout=0.1)
            except Exception as exc:
                try:
                    result_queue.put((False, None, f'{type(exc).__name__}: {exc}'), timeout=0.1)
                except queue.Full:
                    pass

        thread = threading.Thread(target=worker, daemon=True, name='shury-bounded-call')
        thread.start()
        try:
            return result_queue.get(timeout=max(0.001, float(timeout_seconds)))
        except queue.Empty:
            return False, None, 'execution timeout'

    def _run_action(self, state: CognitiveState, action: PlannedAction, outputs: dict[str, Any],
                    approve: Callable[[str, dict[str, Any]], bool], deadline: float | None = None) -> tuple[bool, Any, str | None, bool, float]:
        tool = self.registry.get(action.tool)
        if tool is None:
            return False, None, f'الأداة {action.tool} غير مسجلة.', False, 0.0
        # Company authorization is a runtime gate, not documentation. The CEO-issued
        # assignment must exist for this step, and the current structured ownership
        # proof must still resolve to the same department before the tool executes.
        assignment = next((
            item for item in (getattr(state, 'company_assignments', []) or ())
            if str(item.get('step_id', '')) == str(action.step_id)
        ), None)
        if assignment is None:
            state.event('company_authorization_failed', step=action.step_id, tool=action.tool, reason='missing_assignment')
            return False, None, 'الخطوة لا تملك تفويضًا من شركة SHURY.', False, 0.0
        try:
            expected = self.company.route_plan(
                state.goal.objective if state.goal else state.user_text, [action], tool_registry=self.registry
            )[0]
            if str(expected.department) != str(assignment.get('department')):
                state.event('company_authorization_failed', step=action.step_id, tool=action.tool,
                            reason='department_ownership_changed',
                            assigned_department=assignment.get('department'), expected_department=expected.department)
                return False, None, 'تغير مالك الخطوة تنظيميًا، لذلك أوقفت الشركة التنفيذ حتى يعاد التفويض.', False, 0.0
            if action.skill_key:
                mandate = self.company.mandate(expected, str(action.skill_key))
                if not mandate.authorize(str(action.skill_key), str(assignment.get('department'))):
                    state.event('company_authorization_failed', step=action.step_id, tool=action.tool, reason='mandate_rejected')
                    return False, None, 'تفويض الشركة لا يسمح بتنفيذ هذه المهارة داخل القسم الحالي.', False, 0.0
            state.event('company_authorization_check', step=action.step_id, tool=action.tool,
                        department=assignment.get('department'), specialist=assignment.get('specialist'), allowed=True)
        except Exception as exc:
            state.event('company_authorization_failed', step=action.step_id, tool=action.tool, reason=f'{type(exc).__name__}: {exc}')
            return False, None, f'تعذر إثبات تفويض الشركة للخطوة: {exc}', False, 0.0
        coordination = getattr(state, 'company_coordination', {}) or {}
        objective = state.goal.objective if state.goal else state.user_text
        context = self.company.registry.build_execution_context(
            assignment=assignment, objective=objective, coordination=coordination,
            arg_keys=(action.args or {}).keys(), evidence_refs=(), artifact_refs=(),
            tool_registry=self.registry,
        )
        try:
            if not context.authorize_tool(action.tool):
                raise CompanyContextViolation(f'tool {action.tool} is outside the {context.department} context')
            if not context.authorize_capability(str(action.capability or '')):
                raise CompanyContextViolation(f'capability {action.capability} is outside the task context')
            assert_references_allowed(action.args, context)
        except CompanyContextViolation as exc:
            state.company_active_context = context.to_dict()
            state.company_execution_contexts[context.task_id] = context.to_dict()
            state.event('company_context_violation', step=action.step_id, department=context.department,
                        specialist=context.specialist, reason=str(exc))
            return False, None, str(exc), False, 0.0
        state.company_active_context = context.to_dict()
        state.company_execution_contexts[context.task_id] = context.to_dict()
        state.event('company_execution_context', **context.to_dict())
        args = self._resolve_action_args(action, outputs, allowed_dependencies=set(context.dependency_steps))
        covered, coverage_error = self._validate_action_coverage(state, action, args)
        if not covered:
            return False, None, coverage_error, False, 0.0
        if deadline is not None and time.monotonic() >= deadline:
            return False, None, 'انتهت الميزانية الزمنية قبل تنفيذ الخطوة.', False, 0.0
        errors = tool.validate_args(args)
        if errors:
            return False, None, '; '.join(errors), False, 0.0
        governance_context = GovernanceContext(
            task_id=context.task_id,
            department=context.department,
            specialist=context.specialist,
            skill_key=str(action.skill_key or assignment.get('skill_key') or ''),
            capability=str(action.capability or assignment.get('capability') or ''),
        )
        governance = CompanyGovernance(self.company)
        governance_decision = governance.evaluate(assignment, tool, governance_context, args)
        state.event('company_governance_decision', step=action.step_id, tool=tool.name,
                    **governance_decision.to_dict())
        approval_granted = False
        if not governance_decision.allowed:
            state.event('company_governance_denied', step=action.step_id, tool=tool.name,
                        reasons=list(governance_decision.reasons), risk=governance_decision.risk,
                        action_class=governance_decision.action_class)
            reason = '; '.join(governance_decision.reasons) or 'company governance denied this action'
            return False, None, f'تم رفض العملية بواسطة حوكمة الشركة: {reason}', False, 0.0
        if governance_decision.human_approval_required:
            approval = governance_decision.approval
            before_fingerprint = approval.action_fingerprint if approval else ''
            state.event('company_governance_approval_requested', step=action.step_id, tool=tool.name,
                        request_id=approval.request_id if approval else '',
                        action_fingerprint=before_fingerprint, risk=governance_decision.risk,
                        reviewers=list(governance_decision.reviewers))
            approval_granted = bool(approve(tool.name, dict(args)))
            after_fingerprint = governance.action_fingerprint(task_id=context.task_id, tool=tool, args=dict(args))
            if approval_granted and before_fingerprint and after_fingerprint != before_fingerprint:
                state.event('company_governance_approval_scope_changed', step=action.step_id, tool=tool.name,
                            request_id=approval.request_id if approval else '',
                            expected_fingerprint=before_fingerprint, actual_fingerprint=after_fingerprint)
                return False, None, 'تم رفض العملية بواسطة حوكمة الشركة لأن نطاق الموافقة تغيّر.', False, 0.0
            if not approval_granted:
                state.event('company_governance_approval_rejected', step=action.step_id, tool=tool.name,
                            request_id=approval.request_id if approval else '',
                            action_fingerprint=before_fingerprint)
                return False, None, 'تم رفض العملية التي تحتاج موافقة حوكمة الشركة.', False, 0.0
            state.event('company_governance_approval_granted', step=action.step_id, tool=tool.name,
                        request_id=approval.request_id if approval else '',
                        action_fingerprint=before_fingerprint)

        policy = check_tool(tool, args)
        state.event('policy_check', step=action.step_id, tool=tool.name,
                    allowed=policy.allowed, approval_required=policy.approval_required, reason=policy.reason)
        if not policy.allowed:
            return False, None, policy.reason or 'operation blocked by runtime policy', False, 0.0
        if policy.approval_required and not approval_granted:
            if not approve(tool.name, dict(args)):
                return False, None, 'تم رفض العملية التي تحتاج موافقة.', False, 0.0
        started = time.monotonic()
        from app.runtime.memory_context import (
            current_memory_owner, current_memory_run, push_memory_context, pop_memory_context,
        )
        memory_context_token = push_memory_context(
            owner_id=current_memory_owner() or self.memory.default_owner_id,
            session_id=state.session_id,
            run_id=current_memory_run(),
        )
        try:
            with company_context(context):
                remaining = (deadline - time.monotonic()) if deadline is not None else None
                result = self._bounded_tool_run(tool, args, remaining)
        finally:
            pop_memory_context(memory_context_token)
        # Store only structural output metadata in the department context; raw results remain
        # transient in the execution engine and are exposed to other tasks only through an
        # explicit dependency/handoff.
        context_after = context.to_dict()
        if isinstance(result.data, dict):
            produced = tuple(sorted(str(k) for k in result.data.keys()))
            context_after['produced_output_keys'] = list(produced)
            context_after['output_summary'] = f'dict:{len(result.data)} keys'
        else:
            context_after['output_summary'] = f'type:{type(result.data).__name__}'
        state.company_execution_contexts[context.task_id] = context_after
        elapsed = time.monotonic() - started
        verified, verification_error = verify_step(tool, args, result)
        if result.ok and verified:
            goal_verified, goal_error = self._filesystem_goal_postcondition(state, action, result.data)
            if not goal_verified:
                verified = False
                verification_error = goal_error
        state.company_active_context = {}
        state.event('action_observed', step=action.step_id, tool=action.tool, ok=result.ok,
                    verified=verified, duration_ms=round(elapsed * 1000, 3),
                    error=result.error or verification_error or '')
        if result.ok and verified:
            return True, result.data, None, True, elapsed
        if result.ok and not verified:
            return False, result.data, verification_error or 'verification failed', True, elapsed
        return False, result.data, result.error or 'execution failed', True, elapsed

    @staticmethod
    def _action_spec(action: PlannedAction, tool: Tool, args: dict[str, Any], *, attempt: int = 1) -> ActionSpec:
        return ActionSpec(
            action_id=f'{action.step_id}:attempt:{attempt}',
            capability=str(action.capability or getattr(tool, 'capability', None) or action.tool),
            tool=action.tool,
            parameters=tuple(sorted((str(k), v) for k, v in args.items())),
            preconditions=tuple(sorted(getattr(tool, 'preconditions', ()) or ())),
            expected_effects=tuple(sorted(action.expected_effects or getattr(tool, 'produces', ()) or ())),
            risk=str(getattr(tool, 'risk', 'low')),
            cost=float(getattr(tool, 'cost', 1.0) or 0.0),
            reversible=bool(getattr(tool, 'reversible', False)),
            execution_time=float(getattr(tool, 'duration', 0.0) or 0.0),
            uncertainty=1.0,
        )

    def _refresh_company_assignments(self, state: CognitiveState) -> None:
        """Re-route company ownership after a runtime replanning event.

        The company contract belongs to the current plan, not to a stale pre-replan plan.
        """
        assignments = self.company.route_plan(
            state.goal.objective if state.goal else state.user_text, state.plan, tool_registry=self.registry,
            project_id=str(getattr(state, 'company_project_id', '') or ''),
            horizon=str(getattr(state.goal, 'horizon', 'medium') if state.goal else 'medium'),
        )
        state.company_coordination = self.company.coordinate(
            state.goal.objective if state.goal else state.user_text, assignments, tool_registry=self.registry
        ).to_dict()
        if state.company_project_id:
            try:
                synced = self.company.portfolio.sync_coordination(state.company_project_id, state.company_coordination)
                state.event('company_project_tasks_synced', project_id=state.company_project_id, task_count=len(synced))
                state.company_portfolio = self.company.portfolio.snapshot()
            except Exception as exc:
                state.event('company_project_task_sync_error', project_id=state.company_project_id, error=f'{type(exc).__name__}: {exc}')
                raise
        state.event('company_executive_decomposition',
                    workstreams=state.company_coordination.get('workstreams', []),
                    execution_waves=state.company_coordination.get('execution_waves', []),
                    handoffs=state.company_coordination.get('handoffs', []),
                    critical_path=state.company_coordination.get('critical_path', []),
                    required_capabilities=state.company_coordination.get('required_capabilities', []),
                    unresolved_capabilities=state.company_coordination.get('unresolved_capabilities', []),
                    validation_errors=state.company_coordination.get('validation_errors', []),
                    team_formation=state.company_coordination.get('team_formation', {}))
        state.company_assignments = [
            {
                **assignment.to_dict(),
                'mandate': self.company.mandate(
                    assignment,
                    str(getattr(state.plan[i], 'skill_key', '') or '')
                ).to_dict() if str(getattr(state.plan[i], 'skill_key', '') or '') else {},
            }
            for i, assignment in enumerate(assignments)
        ]
        state.company_assignment = dict(state.company_assignments[0]) if state.company_assignments else {}
        state.event('company_workflow_rerouted', assignments=state.company_assignments, coordination=state.company_coordination)
        for item in state.company_assignments:
            state.event('company_delegation', **item)

    @staticmethod
    def _safe_learning_output(output: Any) -> str:
        text = str(output if output is not None else "")
        return text[:500]

    def _learning_proxy(self, state: CognitiveState, raw_transitions: list[dict[str, Any]], *, status: str, run_id: str):
        """Adapt the canonical Brain episode to the existing Layer-5 learning lifecycle."""
        plan_steps = []
        for index, transition in enumerate(raw_transitions, 1):
            action = transition.get('action') or {}
            outcome = transition.get('outcome') or {}
            plan_steps.append(PlanStep(
                id=str(dict(transition.get('metadata') or ()).get('step_id') or f's{index}'),
                tool=str(action.get('tool') or ''),
                args=dict(action.get('parameters') or {}),
                capability=str(action.get('capability') or action.get('tool') or ''),
                status='done' if bool(transition.get('verified')) else 'failed',
                output=outcome.get('output') if isinstance(outcome, dict) else None,
                error=(str(outcome.get('error') or '') if isinstance(outcome, dict) else ''),
                attempts=max(1, int(outcome.get('attempt') or 1)) if isinstance(outcome, dict) else 1,
                depends_on=[],
            ))
        initial_signature = str(getattr(self, "_learning_initial_state", "") or state.to_canonical_state().fingerprint())
        proxy = SimpleNamespace(
            run_id=run_id,
            goal=state.goal.objective if state.goal else state.user_text,
            operation=str(getattr(state.semantic, "requested_operation", "") or ""),
            status=status,
            replans=int(getattr(self, "_learning_replans", 0) or 0),
            semantic_domain='brain',
            semantic=SimpleNamespace(interaction_shape='atomic'),
            trace=tuple(getattr(state, 'trace', ()) or ()),
            world=SimpleNamespace(
                session_id=state.session_id,
                fingerprint=lambda: initial_signature,
            ),
            plan=Plan(plan_steps),
        )
        return proxy

    @staticmethod
    def _exploration_uncertainty(state: CognitiveState) -> float:
        """Estimate decision-relevant uncertainty for an information action.

        This is a transparent state/evidence signal used only to measure realized
        information gain. It never creates synthetic experience or execution authority.
        """
        frame = state.semantic
        unresolved = tuple(getattr(frame, 'uncertainty', ()) or ()) if frame else ()
        blocking = [item for item in unresolved if item not in {'question_operation_unknown'}]
        unresolved_term = min(1.0, len(set(blocking)) / 2.0)
        evidence_deficit = 1.0 / math.sqrt(len(state.evidence) + 1.0)
        recent_failures = sum(
            1 for event in state.trace[-8:]
            if event.get('kind') == 'action_observed' and not event.get('ok')
        )
        failure_term = min(1.0, recent_failures / 2.0)
        return max(0.0, min(1.0, 0.55 * unresolved_term + 0.35 * evidence_deficit + 0.10 * failure_term))

    def _record_exploration_selection(self, state: CognitiveState, action: PlannedAction, run_id: str) -> int | None:
        if not action.exploration_mode or not hasattr(self.learning, 'exploration_policy'):
            return None
        event = next((item for item in reversed(state.trace) if item.get('kind') == 'exploration_decision'), None)
        if not event or not action.exploration_mode:
            return None
        try:
            uncertainty_before = float(self._exploration_uncertainty(state))
            event_id = self.learning.store.record_exploration_event(
                run_id=run_id,
                state_signature=str(event.get('state_signature') or state.to_canonical_state().fingerprint()),
                action_signature=str(event.get('selected_action_signature') or ''),
                tool=str(action.tool), action=dict(event.get('selected_action') or {'tool': action.tool, 'parameters': dict(action.args or {})}),
                mode=str(event.get('mode') or action.exploration_mode), score=float(event.get('score') or 0.0),
                goal_alignment=float(event.get('goal_alignment') or 0.0), exploitation=float(event.get('exploitation') or 0.0),
                ucb_bonus=float(event.get('ucb_bonus') or 0.0), information_gain=float(event.get('information_gain') or action.information_gain),
                novelty=float(event.get('novelty') or 0.0), relearning_pressure=float(event.get('relearning_pressure') or 0.0),
                risk_penalty=float(event.get('risk_penalty') or 0.0), evidence_count=int(event.get('evidence_count') or 0),
                uncertainty_before=uncertainty_before,
                selected=True, executed=False,
            )
            state.event('exploration_selection', event_id=int(event_id), tool=str(action.tool),
                        mode=str(event.get('mode') or action.exploration_mode), uncertainty_before=uncertainty_before)
            return event_id
        except Exception as exc:
            state.event('exploration_persistence_error', error=f'{type(exc).__name__}: {exc}')
            return None

    def _complete_exploration_event(self, state: CognitiveState, event_id: int | None, *, executed: bool,
                                    ok: bool | None, verified: bool | None, reward: float | None,
                                    prediction_error: float | None = None) -> None:
        if event_id is None:
            return
        try:
            after = float(self._exploration_uncertainty(state))
            selected = next((e for e in reversed(state.trace)
                             if e.get('kind') == 'exploration_selection' and int(e.get('event_id') or -1) == int(event_id)), None)
            before = float(selected.get('uncertainty_before')) if selected and selected.get('uncertainty_before') is not None else after
            realized = max(0.0, min(1.0, before - after)) if executed and ok and verified else 0.0
            self.learning.store.complete_exploration_event(
                int(event_id), executed=executed, ok=ok, verified=verified, reward=reward,
                prediction_error=prediction_error, uncertainty_after=after,
                realized_information_gain=realized,
            )
            if executed and reward is not None and selected:
                arm_signature = str(selected.get('selected_action_signature') or selected.get('action_signature') or '')
                state_signature = str(selected.get('state_signature') or state.to_canonical_state().fingerprint())
                if arm_signature:
                    self.learning.store.record_bandit_observation(
                        state_signature=state_signature, arm_signature=arm_signature, reward=max(0.0, min(1.0, float(reward))),
                        source_event_id=int(event_id),
                    )
            state.event('exploration_feedback', event_id=int(event_id), uncertainty_before=before,
                        uncertainty_after=after, realized_information_gain=realized,
                        executed=bool(executed), ok=ok, verified=verified)
        except Exception as exc:
            state.event('exploration_feedback_error', error=f'{type(exc).__name__}: {exc}', event_id=int(event_id))

    def _replan_after_exploration(self, state: CognitiveState, *, explored_tool: str) -> list[PlannedAction]:
        if not state.semantic or not state.goal:
            return []
        try:
            self.retrieve(state)
            state.candidates = discover_candidates(state.semantic, self.registry)
            return plan(
                state.goal, state.semantic, state.candidates, state=state,
                experiences=self.experiences, avoid_tools={explored_tool},
                learning=self.learning, registry=self.registry, allow_exploration=False,
            )
        except Exception as exc:
            state.event('post_exploration_replan_error', error=f'{type(exc).__name__}: {exc}')
            return []

    @staticmethod
    def _clone_state_for_parallel_action(state: CognitiveState) -> CognitiveState:
        """Create an isolated execution view for one parallel-safe tool call.

        Tools receive arguments rather than the CognitiveState, so the clone only needs the
        read-side planning/organization fields plus fresh per-action mutation containers.
        Shared durable stores are intentionally not copied; parallel execution is opt-in via
        Tool.parallel_safe and remains subject to the existing tool policy.
        """
        local = copy.copy(state)
        local.plan = list(state.plan)
        local.company_assignments = list(state.company_assignments)
        local.company_coordination = dict(state.company_coordination)
        local.company_execution_contexts = {}
        local.company_active_context = {}
        local.observations = []
        local.trace = []
        local.world_facts = dict(state.world_facts)
        local.uncertainties = list(state.uncertainties)
        local.action_specs = list(state.action_specs)
        return local

    def _run_company_parallel_batch(
        self,
        state: CognitiveState,
        actions: tuple[PlannedAction, ...],
        outputs: dict[str, Any],
        approve: Callable[[str, dict[str, Any]], bool],
    ) -> list[tuple[PlannedAction, CognitiveState, tuple[bool, Any, str | None, bool, float]]]:
        """Execute a scheduler-approved batch concurrently with isolated transient state."""
        results: list[tuple[PlannedAction, CognitiveState, tuple[bool, Any, str | None, bool, float]]] = []
        workers = max(2, min(len(actions), 8))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='shury-company') as pool:
            futures = {}
            for action in actions:
                local_state = self._clone_state_for_parallel_action(state)
                futures[pool.submit(self._run_action, local_state, action, dict(outputs), approve)] = (action, local_state)
            completed: dict[str, tuple[PlannedAction, CognitiveState, tuple[bool, Any, str | None, bool, float]]] = {}
            for future in as_completed(futures):
                action, local_state = futures[future]
                try:
                    outcome = future.result()
                except Exception as exc:
                    outcome = (False, None, f'{type(exc).__name__}: {exc}', False, 0.0)
                completed[action.step_id] = (action, local_state, outcome)
        for action in actions:
            results.append(completed[action.step_id])
        return results

    @staticmethod
    def _merge_parallel_state(state: CognitiveState, local_state: CognitiveState) -> None:
        """Merge only per-action observations, trace, contexts and state facts."""
        state.trace.extend(local_state.trace)
        state.observations.extend(local_state.observations)
        for key, value in local_state.company_execution_contexts.items():
            state.company_execution_contexts[key] = value
        state.world_facts.update(local_state.world_facts)

    def _execute_result(self, result: BrainResult, *, approve: Callable[[str, dict[str, Any]], bool] | None = None,
                        max_steps: int = 8, execution_guard: Callable[[], bool] | None = None, deadline: float | None = None) -> BrainResult:
        state = result.state
        if not state.decision or state.decision.kind not in {'execute', 'research'}:
            if state.decision and state.decision.kind == 'retrieve' and state.semantic:
                state.evidence = rank_beliefs([b.to_dict() for b in state.beliefs], state.semantic.slot('query') or state.semantic.text, limit=8)
                state.decision = deliberate(state)
                response = compose(state.decision, state)
            else:
                response = result.response
            try:
                self.memory.observe(
                    state.user_text,
                    assistant_text=response,
                    outcome='needs_user' if state.decision and state.decision.kind == 'clarify' else 'completed',
                    session_id=state.session_id,
                    run_id=result.run_id,
                    experience_kind='interaction',
                    entities=[
                        {"type": str(entity[0]), "text": str(entity[1])}
                        for entity in (tuple(getattr(state.semantic, 'entities', ()) or ()))
                        if isinstance(entity, (tuple, list)) and len(entity) >= 2
                    ],
                    metadata={"runtime": "brain", "decision_kind": state.decision.kind if state.decision else None},
                )
                state.event('episodic_memory_recorded', tool_events=0)
            except Exception as exc:
                state.event('episodic_memory_error', error=f'{type(exc).__name__}: {exc}')
            terminal_status = 'needs_user' if state.decision and state.decision.kind == 'clarify' else 'completed'
            return BrainResult(state, response, result.runtime_state, status=terminal_status, run_id=result.run_id)

        outputs: dict[str, Any] = {}
        pending = list(state.plan)
        executed = 0
        replans = 0
        status = 'completed'
        final = ''
        state.run_id = result.run_id
        self._learning_initial_state = state.to_canonical_state().fingerprint()
        self._learning_replans = 0
        # Security invariant: an approval-gated action must never execute implicitly.
        # Canonical callers must provide an explicit approval decision.
        approver = approve or (lambda _tool, _args: False)
        failed_tools: set[str] = set()
        learning_transitions: list[dict[str, Any]] = []
        state.event('deliberation_start', plan_length=len(pending))

        from app.organization.recovery import CompanyRecoveryManager
        company_recovery = CompanyRecoveryManager()
        recovery_attempted_steps: set[str] = set()

        company_scheduler = CompanyScheduler(default_max_parallelism=4)
        state.event(
            'company_execution_schedule',
            schedule=(getattr(state, 'company_coordination', {}) or {}).get('execution_schedule', []),
            max_parallelism=(getattr(state, 'company_coordination', {}) or {}).get('schedule_max_parallelism', 4),
            estimated_duration=(getattr(state, 'company_coordination', {}) or {}).get('schedule_estimated_duration', 0.0),
        )

        while pending:
            if deadline is not None and time.monotonic() >= deadline:
                status = 'timeout'
                final = 'انتهت الميزانية الزمنية قبل اكتمال التنفيذ والتحقق.'
                state.event('execution_time_budget_exceeded_during_execution')
                break
            if execution_guard is not None:
                try:
                    if not execution_guard():
                        status = 'cancelled'
                        final = 'تم إيقاف التنفيذ لأن حيازة العملية انتهت، ولن تُستكمل خطوات إضافية.'
                        state.event('execution_lease_lost')
                        break
                except Exception:
                    status = 'cancelled'
                    final = 'تم إيقاف التنفيذ لتعذر التحقق من حيازة العملية.'
                    state.event('execution_guard_error')
                    break
            if executed >= max_steps:
                status = 'max_steps'
                final = 'أوقفت التنفيذ عند الحد المسموح للخطوات.'
                state.event('execution_limit', max_steps=max_steps)
                break

            remaining_slots = max(1, max_steps - executed)
            batch = company_scheduler.ready_batch(
                pending, outputs, self.registry, limit=min(company_scheduler.default_max_parallelism, remaining_slots)
            )
            if not batch:
                status = 'failed'
                blocked = pending[0] if pending else None
                final = f'توقفت لأن خطوة {getattr(blocked, "step_id", "unknown")} تعتمد على نتيجة لم تتوفر.'
                state.event('plan_invariant_violation', step=getattr(blocked, 'step_id', 'unknown'),
                            depends_on=list(getattr(blocked, 'depends_on', ()) or ()))
                break

            selected_ids = {action.step_id for action in batch}
            pending = [action for action in pending if action.step_id not in selected_ids]
            # Capture learning/exploration metadata BEFORE any action in the batch runs.
            batch_meta: dict[str, tuple[dict[str, Any], Any, Any, int | None]] = {}
            batch_state_before = state.to_canonical_state().fingerprint()
            for action in batch:
                tool = self.registry.get(action.tool)
                resolved_args = self._resolve_action_args(action, outputs)
                action_spec = self._action_spec(action, tool, resolved_args) if tool else None
                prediction = None
                if action_spec is not None:
                    try:
                        prediction = self.learning.transition_model.predict(batch_state_before, action_spec.to_dict())
                    except Exception:
                        prediction = None
                exploration_event_id = None
                if len(batch) == 1:
                    exploration_event_id = self._record_exploration_selection(state, action, result.run_id)
                batch_meta[action.step_id] = (resolved_args, action_spec, prediction, exploration_event_id)

            if len(batch) > 1 and deadline is None:
                state.event('company_parallel_batch_started', task_ids=[a.step_id for a in batch],
                            tools=[a.tool for a in batch], batch_size=len(batch))
                batch_results = self._run_company_parallel_batch(state, batch, outputs, approver)
                state.event('company_parallel_batch_completed', task_ids=[a.step_id for a in batch],
                            batch_size=len(batch))
            else:
                action = batch[0]
                local_state = state
                batch_results = [(action, local_state,
                                  self._run_action(state, action, outputs, approver))]

            replan_request: tuple[str, str] | None = None
            batch_failure = False
            lease_lost = False
            for action, local_state, action_result in batch_results:
                if local_state is not state:
                    self._merge_parallel_state(state, local_state)

                ok, output, error, executed_action, duration = action_result
                resolved_args, action_spec, prediction, exploration_event_id = batch_meta[action.step_id]
                state_before = batch_state_before

                if len(batch) == 1 and execution_guard is not None:
                    try:
                        if not execution_guard():
                            status = 'cancelled'
                            final = 'تم إيقاف التنفيذ لأن حيازة العملية انتهت.'
                            state.event('execution_lease_lost_after_action', step=action.step_id)
                            break
                    except Exception:
                        status = 'cancelled'
                        final = 'تم إيقاف التنفيذ لتعذر التحقق من حيازة العملية بعد الخطوة.'
                        state.event('execution_guard_error_after_action', step=action.step_id)
                        break

                if not ok:
                    # C9: record organizational execution evidence before any recovery decision.
                    try:
                        assignment = next((a for a in state.company_assignments if str(a.get('step_id')) == str(action.step_id)), {})
                        capability = str(action.capability or assignment.get('capability') or '')
                        learning_store = getattr(self.learning, 'store', None)
                        if learning_store is not None and executed_action:
                            learning_store.record_company_delegation_outcome(
                                capability=capability, department=str(assignment.get('department') or ''),
                                specialist=str(assignment.get('specialist') or ''), skill_key=str(assignment.get('skill_key') or action.skill_key or ''),
                                tool=action.tool, verified=False, duration=duration, run_id=result.run_id,
                                failure_class=company_recovery.classify_failure(str(error or ''), verification_failed=False),
                            )
                    except Exception as exc:
                        state.event('company_delegation_evidence_error', error=f'{type(exc).__name__}: {exc}')

                    self._complete_exploration_event(state, exploration_event_id, executed=executed_action, ok=False, verified=False, reward=0.0)
                    if executed_action:
                        state_after = state.to_canonical_state().fingerprint()
                        learning_transitions.append({
                            'state_before': state_before,
                            'action': action_spec.to_dict() if action_spec else {},
                            'predicted_state': prediction.predicted_state if prediction else None,
                            'state_after': state_after,
                            'outcome': {'ok': False, 'verified': False, 'error': str(error or 'execution failed'),
                                        'duration_ms': duration * 1000.0, 'attempt': 1},
                            'verified': False,
                            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                            'metadata': (('step_id', action.step_id),),
                        })
                    # _run_action already recorded company/tool observations for executed failures.
                    if not any(item.get('step_id') == action.step_id and item.get('error') == str(error or 'execution failed')
                               for item in state.observations[-3:]):
                        state.observations.append({
                            'step_id': action.step_id, 'tool': action.tool, 'ok': False,
                            'error': str(error or 'execution failed'), 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        })
                    failed_tools.add(action.tool)
                    state.world_facts[f'action_failed:{action.tool}'] = True
                    if replan_request is None and error and 'تم رفض' not in str(error):
                        replan_request = (action.tool, str(error))
                    batch_failure = True
                    continue

                if not self._verify_output(action, output):
                    try:
                        assignment = next((a for a in state.company_assignments if str(a.get('step_id')) == str(action.step_id)), {})
                        learning_store = getattr(self.learning, 'store', None)
                        if learning_store is not None and executed_action:
                            learning_store.record_company_delegation_outcome(
                                capability=str(action.capability or assignment.get('capability') or ''),
                                department=str(assignment.get('department') or ''), specialist=str(assignment.get('specialist') or ''),
                                skill_key=str(assignment.get('skill_key') or action.skill_key or ''), tool=action.tool, verified=False,
                                duration=duration, run_id=result.run_id, failure_class='verification',
                            )
                    except Exception as exc:
                        state.event('company_delegation_evidence_error', error=f'{type(exc).__name__}: {exc}')
                    self._complete_exploration_event(state, exploration_event_id, executed=executed_action, ok=True, verified=False, reward=0.0)
                    state.observations.append({
                        'step_id': action.step_id, 'tool': action.tool, 'ok': True,
                        'verified': False, 'error': 'verification failed',
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    })
                    if executed_action:
                        state_after = state.to_canonical_state().fingerprint()
                        learning_transitions.append({
                            'state_before': state_before,
                            'action': action_spec.to_dict() if action_spec else {},
                            'predicted_state': prediction.predicted_state if prediction else None,
                            'state_after': state_after,
                            'outcome': {'ok': True, 'verified': False, 'error': 'verification failed',
                                        'duration_ms': duration * 1000.0, 'attempt': 1},
                            'verified': False,
                            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                            'metadata': (('step_id', action.step_id),),
                        })
                    batch_failure = True
                    final = f'نفذت {action.tool} لكن التحقق من النتيجة لم ينجح.'
                    state.event('verification_failed', step=action.step_id, tool=action.tool)
                    if replan_request is None:
                        replan_request = (action.tool, 'verification failed: ' + str(error or 'verification failed'))
                    continue

                try:
                    assignment = next((a for a in state.company_assignments if str(a.get('step_id')) == str(action.step_id)), {})
                    capability = str(action.capability or assignment.get('capability') or '')
                    learning_store = getattr(self.learning, 'store', None)
                    if learning_store is not None:
                        learning_store.record_company_delegation_outcome(
                            capability=capability, department=str(assignment.get('department') or ''),
                            specialist=str(assignment.get('specialist') or ''), skill_key=str(assignment.get('skill_key') or action.skill_key or ''),
                            tool=action.tool, verified=True, duration=duration, run_id=result.run_id, failure_class='',
                        )
                except Exception as exc:
                    state.event('company_delegation_evidence_error', error=f'{type(exc).__name__}: {exc}')

                outputs[action.step_id] = output
                executed += 1
                resolved_action = replace(action, args=resolved_args)
                state.plan = [resolved_action if step.step_id == action.step_id else step for step in state.plan]
                self._observe_output(state, resolved_action, output)
                self._complete_exploration_event(state, exploration_event_id, executed=executed_action, ok=True, verified=True, reward=1.0)
                if executed_action:
                    state_after = state.to_canonical_state().fingerprint()
                    learning_transitions.append({
                        'state_before': state_before,
                        'action': action_spec.to_dict() if action_spec else {},
                        'predicted_state': prediction.predicted_state if prediction else None,
                        'state_after': state_after,
                        'outcome': {'ok': True, 'verified': True, 'error': '',
                                    'duration_ms': duration * 1000.0, 'attempt': 1,
                                    'output_summary': self._safe_learning_output(output)},
                        'verified': True,
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'metadata': (('step_id', action.step_id),),
                    })
                state.event('step_completed', step=action.step_id, tool=action.tool,
                            executed_steps=executed, replans=replans)
                if state.company_project_id:
                    try:
                        self.company.portfolio.mark_task_status(state.company_project_id, action.step_id, 'completed')
                    except Exception as exc:
                        state.event('company_project_task_status_error', project_id=state.company_project_id, task_id=action.step_id, error=f'{type(exc).__name__}: {exc}')

                if action.exploration_mode and executed < max_steps:
                    replacement = self._replan_after_exploration(state, explored_tool=action.tool)
                    if replacement:
                        replan_request = None
                        replans += 1
                        self._learning_replans = replans
                        state.plan = replacement
                        self._refresh_company_assignments(state)
                        state.event('exploration_replan', explored_tool=action.tool, mode=action.exploration_mode,
                                    information_gain=action.information_gain, new_plan=[x.to_dict() for x in replacement])
                        pending = replacement + pending
                        break

            if deadline is not None and time.monotonic() >= deadline:
                status = 'timeout'
                final = 'انتهت الميزانية الزمنية قبل اكتمال التحقق من الخطوة.'
                state.event('execution_time_budget_exceeded_after_batch')
            if len(batch) > 1 and execution_guard is not None:
                try:
                    lease_lost = not bool(execution_guard())
                except Exception:
                    lease_lost = True
                if lease_lost:
                    state.event('execution_lease_lost_after_parallel_batch', task_ids=[a.step_id for a in batch])
                    status = 'cancelled'
                    final = 'تم إيقاف التنفيذ لأن حيازة العملية انتهت بعد تشغيل الدفعة المتوازية.'

            if status in {'failed', 'cancelled', 'timeout'}:
                break
            if replan_request is not None:
                failed_tool, failure_reason = replan_request
                failed_action = next((item for item in batch if item.tool == failed_tool), None)
                # C9: recover at the organizational boundary before the generic planner.
                # A failed specialist is not replaced by guesswork; only a qualified alternative
                # with verified same-capability evidence may be selected automatically.
                if failed_action is not None and failed_action.step_id not in recovery_attempted_steps:
                    recovery_attempted_steps.add(failed_action.step_id)
                    assignment = next((a for a in state.company_assignments if str(a.get('step_id')) == str(failed_action.step_id)), {})
                    recovery = company_recovery.decide(
                        action=failed_action, error=failure_reason, organization=self.company.registry,
                        tool_registry=self.registry, learning_store=getattr(self.learning, 'store', None),
                    )
                    state.event('company_recovery_decision', **recovery.to_dict(),
                                assigned_department=assignment.get('department', ''),
                                assigned_specialist=assignment.get('specialist', ''))
                    coordination = dict(getattr(state, 'company_coordination', {}) or {})
                    decisions = list(coordination.get('recovery_decisions') or [])
                    decisions.append(recovery.to_dict())
                    active = list(coordination.get('active_redelegations') or [])
                    if recovery.decision == 'redelegate':
                        replacement_action = company_recovery.redelegate_action(failed_action, recovery, self.registry)
                        if replacement_action is not None:
                            replans += 1
                            self._learning_replans = replans
                            state.plan = [replacement_action if item.step_id == failed_action.step_id else item for item in state.plan]
                            self._refresh_company_assignments(state)
                            active.append({
                                'step_id': failed_action.step_id, 'from_tool': failed_action.tool,
                                'to_tool': replacement_action.tool, 'from_specialist': assignment.get('specialist', ''),
                                'reason': recovery.reason, 'confidence': recovery.confidence,
                            })
                            coordination['recovery_decisions'] = decisions
                            coordination['active_redelegations'] = active
                            state.company_coordination = coordination
                            state.event('company_redelegated', step=failed_action.step_id,
                                        from_tool=failed_action.tool, to_tool=replacement_action.tool,
                                        department=recovery.selected.department if recovery.selected else '',
                                        specialist=recovery.selected.specialist if recovery.selected else '',
                                        confidence=recovery.confidence)
                            pending = [replacement_action] + pending
                            continue
                    coordination['recovery_decisions'] = decisions
                    state.company_coordination = coordination
                    if recovery.decision == 'escalate':
                        status = 'failed'
                        final = f'التنفيذ توقف: {failure_reason}. لم تجد الشركة بديلًا مؤهلًا تدعمه أدلة نجاح موثقة.'
                        state.event('company_recovery_escalated', step=failed_action.step_id, reason=recovery.reason)
                        break
                    if recovery.decision == 'redelegate':
                        status = 'failed'
                        final = f'التنفيذ توقف: {failure_reason}. تعذر تطبيق إعادة التفويض الآمنة.'
                        state.event('company_recovery_escalated', step=failed_action.step_id, reason='selected recovery candidate could not be materialized safely')
                        break

                # Company-owned actions do not fall back to an unrelated generic replan after
                # C9 recovery has been evaluated. This prevents evidence-free reassignment.
                if failed_action is not None:
                    if state.company_project_id:
                        try:
                            self.company.portfolio.mark_task_status(state.company_project_id, failed_action.step_id, 'failed')
                        except Exception as exc:
                            state.event('company_project_task_status_error', project_id=state.company_project_id, task_id=failed_action.step_id, error=f'{type(exc).__name__}: {exc}')
                    status = 'failed'
                    final = f'التنفيذ توقف: {failure_reason}. لا يوجد مسار Company آمن بديل بعد تقييم الاسترجاع.'
                    break

                candidates = discover_candidates(state.semantic, self.registry) if state.semantic else []
                replacement = replan(state.goal, state.semantic, candidates, state=state, experiences=self.experiences,
                                     failed_tool=failed_tool, learning=self.learning, registry=self.registry) if state.goal and state.semantic else []
                if replacement:
                    replans += 1
                    self._learning_replans = replans
                    state.plan = replacement
                    self._refresh_company_assignments(state)
                    state.event('replan', failed_tool=failed_tool, reason='observed_failure',
                                failure=failure_reason,
                                new_plan=[x.to_dict() for x in replacement], replan_count=replans)
                    pending = replacement + pending
                    continue
                status = 'failed'
                final = f'التنفيذ توقف: {failure_reason}'
                break

        skill_verification = {"verified": True, "checks": [], "errors": []}
        if status == 'completed' and state.selected_skill is not None:
            skill_verification = verify_skill_contract(state.selected_skill, state, outputs)
            state.event('skill_verification', selected_skill=getattr(state.selected_skill, 'key', ''), **skill_verification)
            if not skill_verification['verified']:
                status = 'failed'
                final = 'نفذت خطوات المهارة، لكن تحقق المهارة ككل لم يثبت إنجاز الهدف.'
                state.event('skill_verification_failed', selected_skill=getattr(state.selected_skill, 'key', ''),
                            errors=list(skill_verification.get('errors', ())))

        state.event('post_action_evaluation', outputs={k: str(v)[:500] for k, v in outputs.items()},
                    executed_steps=executed, replans=replans)
        company_review = None
        if status == 'completed' and getattr(state, 'company_assignments', None):
            company_operation = str(getattr(state.semantic, 'requested_operation', '') or '')
            company_review = review_company_execution(
                goal=state.goal.objective if state.goal else state.user_text,
                operation=company_operation, plan=state.plan,
                assignments=state.company_assignments, status=status,
                outputs=outputs, observations=state.observations,
                coordination=getattr(state, 'company_coordination', None),
            )
            state.event('company_qa_review', **company_review.to_dict())
            if not company_review.ok:
                status = 'failed'
                final = company_review.reason
            else:
                final = company_review.final_message
        state.company_review = company_review.to_dict() if company_review else {}

        # C11: verify that skills which depend on external evidence actually carry
        # machine-readable provenance from the observed tool outputs. The evidence
        # policy is fail-closed for governed skills and never promotes raw web prose
        # into trusted knowledge.
        state.company_evidence = []
        if status == 'completed' and getattr(state, 'company_assignments', None):
            skill_keys = tuple(dict.fromkeys(str(a.get('skill_key') or '') for a in state.company_assignments if str(a.get('skill_key') or '')))
            for skill_key in skill_keys:
                try:
                    assessment = self.company_evidence.assess_outputs(skill_key, outputs)
                    state.company_evidence.append(assessment.to_dict())
                except Exception as exc:
                    state.company_evidence.append({'skill_key': skill_key, 'ok': False, 'reason': 'evidence_policy_error', 'error': f'{type(exc).__name__}: {exc}'})
            failed_evidence = [item for item in state.company_evidence if not bool(item.get('ok', False))]
            if failed_evidence:
                status = 'failed'
                final = 'التنفيذ اكتمل ظاهريًا، لكن متطلبات provenance للأدلة لم تثبت.'
                state.event('company_evidence_failed', assessments=state.company_evidence)
            else:
                state.event('company_evidence_verified', assessments=state.company_evidence)
        company_outcome_verified = bool(status == 'completed' and (company_review.ok if company_review else True))

        # C10: persist structured organizational knowledge only after execution/review outcome.
        # Raw user text and transient task context are intentionally excluded.
        try:
            assignments = list(getattr(state, 'company_assignments', []) or [])
            for item in assignments:
                self.company_memory.remember_ownership(
                    subject=str(item.get('tool') or item.get('capability') or item.get('skill_key') or item.get('operation') or 'unknown'),
                    department=str(item.get('department') or ''), role=str(item.get('specialist') or item.get('department_head') or ''),
                    skill=str(item.get('skill_key') or ''), capability=str(item.get('capability') or ''), tool=str(item.get('tool') or ''),
                    evidence=(f"company-assignment:{item.get('step_id')}",),
                    project_id=str(getattr(state, 'company_project_id', '') or '') or None,
                )
            coord = dict(getattr(state, 'company_coordination', {}) or {})
            team = dict(coord.get('team_formation') or {})
            if team:
                self.company_memory.remember_decision(
                    decision_key=str(state.goal.name if state.goal else 'company-task'),
                    decision={'status': status, 'departments': list(team.get('departments') or []),
                              'members': list(team.get('members') or []), 'requirement_keys': list(team.get('requirement_keys') or [])},
                    evidence=tuple(str(x) for x in (coord.get('critical_path') or ())), run_id=result.run_id,
                )
            if company_review:
                self.company_memory.remember_review_finding(
                    review_key=str(state.goal.name if state.goal else result.run_id),
                    finding={'ok': bool(company_review.ok), 'reason': company_review.reason, 'checks': list(company_review.checks)},
                    blocking=not bool(company_review.ok), evidence=tuple(str(x) for x in (company_review.checks or ())),
                    run_id=result.run_id,
                    project_id=str(getattr(state, 'company_project_id', '') or '') or None,
                )
            self.company_memory.remember_outcome(
                run_id=result.run_id, status=status,
                summary={'departments': list(dict.fromkeys(str(x.get('department') or '') for x in assignments if x.get('department'))),
                         'tools': list(dict.fromkeys(str(x.get('tool') or '') for x in assignments if x.get('tool'))),
                         'status': status, 'verified': company_outcome_verified, 'review_ok': bool(company_review.ok) if company_review else None,
                         'replans': int(replans), 'project_id': str(getattr(state, 'company_project_id', '') or '')},
                verified=company_outcome_verified,
                project_id=str(getattr(state, 'company_project_id', '') or '') or None,
            )
            if status == 'completed' and (company_review is None or company_review.ok):
                for item in assignments:
                    tool_name, capability = str(item.get('tool') or ''), str(item.get('capability') or '')
                    if tool_name and capability:
                        self.company_memory.remember_procedure(
                            capability=capability, skill=str(item.get('skill_key') or ''), tool=tool_name,
                            procedure={'step_id': str(item.get('step_id') or ''), 'expected_effects': list(item.get('expected_effects') or [])},
                            evidence=(f"verified-run:{result.run_id}",), run_id=result.run_id,
                        )
            if status != 'completed':
                for item in assignments:
                    capability = str(item.get('capability') or '')
                    if capability:
                        self.company_memory.remember_failure_lesson(
                            capability=capability, failure_class='company_execution_failure',
                            lesson={'status': status, 'tool': str(item.get('tool') or ''), 'specialist': str(item.get('specialist') or '')},
                            evidence=(f"failed-run:{result.run_id}",), run_id=result.run_id,
                        )
            state.event('company_memory_persisted', stats=self.company_memory.stats())
        except Exception as exc:
            state.event('company_memory_persistence_error', error=f'{type(exc).__name__}: {exc}')

        if status == 'completed':
            final = compose_action_result(state, action=action if 'action' in locals() else None, output=output if 'output' in locals() else None, all_outputs=outputs)
            verified = True
            reward = 1.0
        else:
            verified = False
            reward = 0.0
        # Phase 8: persist the canonical interaction as episodic experience in Memory.
        # This is deliberately separate from LearningStore experiences: the Memory episode
        # answers "what happened earlier?", while LearningStore remains the optimization substrate.
        try:
            episode_tools = []
            for transition in learning_transitions:
                action_payload = transition.get('action') or {}
                outcome_payload = transition.get('outcome') or {}
                episode_tools.append({
                    "step_id": dict(transition.get('metadata') or ()).get('step_id', ""),
                    "tool": action_payload.get('tool', ""),
                    "capability": action_payload.get('capability', ""),
                    "parameters": action_payload.get('parameters', ()),
                    "output": outcome_payload.get('output_summary'),
                    "error": outcome_payload.get('error') or None,
                    "ok": bool(outcome_payload.get('ok', False)),
                    "verified": bool(transition.get('verified', False)),
                    "duration_ms": outcome_payload.get('duration_ms'),
                    "timestamp": transition.get('timestamp'),
                })
            selected_skill_key = getattr(getattr(state, 'selected_skill', None), 'key', '') or (state.plan[0].skill_key if state.plan else '')
            contract_inputs = {step.step_id: step.args for step in state.plan}
            tools_invoked = [item.get('tool') for item in episode_tools]
            errors_list = [item.get('error') for item in episode_tools if item.get('error')]
            if status != 'completed' and not errors_list:
                errors_list.append(final)
            total_elapsed = round(sum(float(item.get('duration_ms') or 0.0) for item in episode_tools) / 1000.0, 3)
            contract_verified = verified and all(bool(item.get('verified')) for item in episode_tools) if episode_tools else verified

            semantic_entities = [
                {
                    'type': str(getattr(entity, 'type', 'entity') or 'entity'),
                    'text': str(getattr(entity, 'text', '') or getattr(entity, 'canonical', '') or ''),
                }
                for entity in (tuple(getattr(state.semantic, 'entities', ()) or ()))
            ]

            execution_record = {
                'selected_skill': selected_skill_key,
                'inputs': contract_inputs,
                'tools_invoked': tools_invoked,
                'tool_outputs': {k: str(v)[:500] for k, v in outputs.items()},
                'execution_status': status,
                'errors': errors_list,
                'elapsed_execution': total_elapsed,
                'verification_result': contract_verified,
                'skill_verification': skill_verification,
            }
            state.event('execution_record', **execution_record)

            self.memory.observe(
                state.user_text,
                assistant_text=final,
                outcome=status,
                owner_id=None,
                session_id=state.session_id,
                run_id=result.run_id,
                tool_events=episode_tools,
                entities=semantic_entities,
                experience_kind="task" if episode_tools else "interaction",
                metadata={
                    "runtime": "brain",
                    "planner": getattr(state.plan, "planner", None),
                    "replans": replans,
                    "goal_key": str(state.goal.objective if state.goal else state.user_text),
                    "tool_count": len(episode_tools),
                    "verified_steps": sum(1 for item in episode_tools if item.get("verified")),
                    "execution_contract": execution_record,
                },
            )
            state.event('episodic_memory_recorded', tool_events=len(episode_tools))
        except Exception as exc:
            state.event('episodic_memory_error', error=f'{type(exc).__name__}: {exc}')

        proxy = self._learning_proxy(state, learning_transitions, status=status, run_id=result.run_id)
        try:
            learning_result = self.learning.observe_run(
                proxy,
                self.memory,
                trajectory=learning_transitions,
                registry=self.registry,
            ) if learning_transitions else None
            state.self_model = self.self_model.snapshot()
            if learning_result and isinstance(learning_result, dict):
                try:
                    self.learning.store.record_learning_stage(
                        result.run_id, 'self_model_refresh', status='completed',
                        payload={
                            'capabilities': len(state.self_model.get('capabilities', ())),
                            'reliability_rows': len(state.self_model.get('reliability', ())),
                        },
                    )
                    cycle = learning_result.get('learning_cycle')
                    if isinstance(cycle, dict):
                        cycle['self_model_refreshed'] = True
                        learning_result['learning_cycle'] = cycle
                except Exception:
                    pass
            state.event('learning_recorded', verified=verified, reward=reward,
                        transition_count=len(learning_transitions), learning=learning_result,
                        self_model_updated=True)
        except Exception as exc:
            # Learning is important, but it is never allowed to take execution authority or
            # bring down a completed user action. The event makes the degradation inspectable.
            state.event('learning_error', error=f'{type(exc).__name__}: {exc}')
        return BrainResult(state, final, runtime_state={
            'outputs': outputs, 'executed_steps': executed, 'status': status, 'replans': replans,
            'company_assignment': dict(getattr(state, 'company_assignment', {}) or {}),
            'company_assignments': list(getattr(state, 'company_assignments', []) or []),
            'company_review': dict(getattr(state, 'company_review', {}) or {}),
            'company_coordination': dict(getattr(state, 'company_coordination', {}) or {}),
            'company_memory': list(getattr(state, 'company_memory', []) or []),
            'company_evidence': list(getattr(state, 'company_evidence', []) or []),
            'company_project_id': str(getattr(state, 'company_project_id', '') or ''),
            'company_project_context': dict(getattr(state, 'company_project_context', {}) or {}),
            'company_portfolio': dict(getattr(state, 'company_portfolio', {}) or {}),
        }, status=status, run_id=result.run_id)

    def act(self, user_text: str, *, approve: Callable[[str, dict[str, Any]], bool] | None = None,
            session_id: str | None = None, max_steps: int = 8, execution_guard: Callable[[], bool] | None = None, max_seconds: float | None = None) -> BrainResult:
        sid = session_id or uuid.uuid4().hex
        memory_token = push_memory(self.memory)
        try:
            deadline = time.monotonic() + float(max_seconds) if max_seconds is not None else None
            remaining = (deadline - time.monotonic()) if deadline is not None else None
            ok, result, error = self._bounded_call(
                lambda: self.think(user_text, session_id=sid), remaining
            )
            if not ok:
                state = CognitiveState(user_text=user_text, session_id=sid)
                state.event('execution_time_budget_exceeded_during_think' if error == 'execution timeout' else 'think_error',
                            error=error or 'unknown think failure')
                status = 'timeout' if error == 'execution timeout' else 'failed'
                response = 'انتهت الميزانية الزمنية قبل بدء التنفيذ.' if status == 'timeout' else f'فشل التفكير قبل التنفيذ: {error}'
                return BrainResult(state, response, None, status=status, run_id=uuid.uuid4().hex)
            if deadline is not None and time.monotonic() >= deadline:
                result.state.event('execution_time_budget_exceeded_before_execution')
                return BrainResult(result.state, 'انتهت الميزانية الزمنية قبل بدء التنفيذ.', result.runtime_state, status='timeout', run_id=result.run_id)
            return self._execute_result(result, approve=approve, max_steps=max_steps, execution_guard=execution_guard, deadline=deadline)
        finally:
            pop_memory(memory_token)

    def act_structured(self, payload: dict[str, Any] | GoalSpec, *,
                       approve: Callable[[str, dict[str, Any]], bool] | None = None,
                       session_id: str | None = None, max_steps: int = 8, execution_guard: Callable[[], bool] | None = None, max_seconds: float | None = None) -> BrainResult:
        memory_token = push_memory(self.memory)
        try:
            deadline = time.monotonic() + float(max_seconds) if max_seconds is not None else None
            remaining = (deadline - time.monotonic()) if deadline is not None else None
            ok, result, error = self._bounded_call(
                lambda: self.think_structured(payload, session_id=session_id), remaining
            )
            if not ok:
                state = CognitiveState(user_text=str(getattr(payload, 'objective', None) or (payload.get('objective', '') if isinstance(payload, dict) else '')), session_id=session_id)
                state.event('execution_time_budget_exceeded_during_think' if error == 'execution timeout' else 'think_error',
                            error=error or 'unknown think failure')
                status = 'timeout' if error == 'execution timeout' else 'failed'
                response = 'انتهت الميزانية الزمنية قبل بدء التنفيذ.' if status == 'timeout' else f'فشل التفكير قبل التنفيذ: {error}'
                return BrainResult(state, response, None, status=status, run_id=uuid.uuid4().hex)
            if deadline is not None and time.monotonic() >= deadline:
                result.state.event('execution_time_budget_exceeded_before_execution')
                return BrainResult(result.state, 'انتهت الميزانية الزمنية قبل بدء التنفيذ.', result.runtime_state, status='timeout', run_id=result.run_id)
            return self._execute_result(result, approve=approve, max_steps=max_steps, execution_guard=execution_guard, deadline=deadline)
        finally:
            pop_memory(memory_token)

    def _verify_output(self, action: PlannedAction, output: Any) -> bool:
        tool = self.registry.get(action.tool)
        if tool is None:
            return False
        if output is None and str(tool.verification_level).lower() == 'strong':
            return False
        if isinstance(output, dict):
            if output.get('status') == 'abstained' or output.get('grounded') is False:
                return False
            if 'answer_grounded' in action.expected_effects and output.get('answer') is not None:
                return bool(output.get('grounded'))
        if not action.expected_effects:
            return True
        # Effects are only considered observed when the result carries an actual value.
        return output is not None or str(tool.verification_level).lower() != 'strong'

    def _alternative_action(self, state: CognitiveState, failed: PlannedAction) -> PlannedAction | None:
        """Compatibility helper; V23 replanning now uses the state planner directly."""
        if not state.semantic or not state.goal:
            return None
        candidates = discover_candidates(state.semantic, self.registry)
        replacement = replan(state.goal, state.semantic, candidates, state=state, experiences=self.experiences, failed_tool=failed.tool, learning=self.learning, registry=self.registry)
        return replacement[0] if replacement else None

    def _observe_output(self, state: CognitiveState, action: PlannedAction, output: Any) -> None:
        state.observations.append({
            'step_id': action.step_id, 'tool': action.tool, 'ok': True,
            'output_summary': str(output)[:800], 'effects': list(action.expected_effects),
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        })
        for effect in action.expected_effects:
            state.world_facts[effect] = output if len(action.expected_effects) == 1 else True
        if isinstance(output, dict):
            evidence_rows = output.get('evidence') or output.get('sources') or []
            for item in evidence_rows[:8] if isinstance(evidence_rows, list) else []:
                if isinstance(item, dict):
                    content = str(item.get('title') or item.get('snippet') or item.get('summary') or item.get('text') or '').strip()
                    if content:
                        state.evidence.append(Evidence(
                            kind=str(item.get('source_kind') or item.get('source') or 'external_evidence'),
                            content=content[:1000], source=str(item.get('source_kind') or item.get('source') or action.tool),
                            confidence=float(item.get('quality') or item.get('confidence') or 0.5),
                            reference=str(item.get('url') or item.get('id') or ''), provenance=f'action:{action.tool}',
                        ))
            answer = str(output.get('answer') or '').strip()
            if answer and not state.evidence:
                state.evidence.append(Evidence('observed_answer', answer[:1000], action.tool, 0.75, '', f'action:{action.tool}'))
        sid = state.session_id or ''
        if action.tool in {'remember_fact', 'remember_result'}:
            args = action.args
            predicate = str(args.get('key') or '')
            value = args.get('value')
            if predicate and value is not None:
                # The tool already wrote canonical Memory. Refresh only the derived Brain view.
                state.beliefs = self._load_beliefs(sid)
                self._sync_legacy_fact(sid, predicate)
        elif action.tool == 'forget_fact':
            # Deletion is authoritative in canonical Memory. Remove the mirrored LearningStore
            # belief projection as well, then reload so no retrievable derived copy survives.
            predicate = str(action.args.get('key') or '')
            if predicate and sid:
                try:
                    self.experiences.delete_belief(session_id=sid, subject='user', predicate=predicate)
                except Exception:
                    pass
            state.beliefs = self._load_beliefs(sid)
        elif action.tool == 'recall_fact':
            predicate = str(action.args.get('key') or '')
            if predicate:
                beliefs = self._load_beliefs(sid)
                if not any(b.predicate == predicate and b.status == 'active' for b in beliefs):
                    self._sync_legacy_fact(sid, predicate)
                    beliefs = self._load_beliefs(sid)
                state.beliefs = beliefs
                state.evidence = rank_beliefs([b.to_dict() for b in beliefs if b.predicate == predicate], predicate, limit=8)
        elif action.tool == 'calculator':
            self.state_store.append_event(sid, 'observation', {'topic': 'calculation_result', 'value': output})
        elif action.tool == 'get_time':
            self.state_store.append_event(sid, 'observation', {'topic': 'current_time', 'value': output})

    def _compose_observed_answer(self, state: CognitiveState, outputs: dict[str, Any]) -> str:
        if not outputs:
            return compose(state.decision or Decision('respond', 0, ''), state)
        last_step = next(reversed(outputs))
        action = next((x for x in state.observations if x.get('step_id') == last_step), None)
        tool_name = str(action.get('tool') if action else '')
        observed_action = PlannedAction(last_step, tool_name, tool_name, {}, (), (), 'observed action')
        return compose_action_result(state, action=observed_action, output=outputs.get(last_step), all_outputs=outputs)

    def _lesson_from_observation(self, state: CognitiveState) -> str:
        failed = [e for e in state.trace if e.get('kind') == 'action_observed' and not e.get('ok')]
        if failed:
            return f"failure:{failed[-1].get('tool')}:{failed[-1].get('error')}"
        if state.plan:
            return f"verified:{' -> '.join(x.tool for x in state.plan)}"
        return ''

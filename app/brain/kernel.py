from __future__ import annotations

import os
import json
import math
import time
import uuid
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any, Callable

from app.brain.capabilities import build_capabilities, discover_candidates
from app.brain.deliberation import deliberate
from app.brain.inference import infer, rank_beliefs
from app.brain.self_model import SelfModel
from app.brain.models import ActionSpec, Belief, CognitiveState, Evidence, GoalSpec, PlannedAction, SemanticFrame
from app.brain.perception import perceive
from app.brain.planner import make_goal, plan, replan
from app.brain.response import compose, compose_action_result
from app.brain.store import BrainStateStore
from app.knowledge.memory import get_memory
from app.learning.manager import SelfImprovementManager
from app.learning.store import LearningStore
from app.domain.plan import Plan, PlanStep
from app.runtime.registry import Tool, load_tools
from app.runtime.policy import check_tool
from app.runtime.verify import verify_step
from app.brain.structured import validate_structured_goal
from app.intelligence.semantic import semantic_understand
from app.runtime.memory_context import push_memory, pop_memory


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
                 learning_manager: SelfImprovementManager | None = None):
        self.memory = memory or get_memory()
        self.registry = registry or load_tools()
        self.state_store = state_store or BrainStateStore()
        learning_store = None
        if isinstance(experience_store, LearningStore):
            learning_store = experience_store
        elif experience_store is not None:
            learning_store = getattr(experience_store, 'store', None)
        self.learning = learning_manager or SelfImprovementManager(store=learning_store)
        self.experiences = self.learning.store
        self.self_model = SelfModel(self.registry, self.experiences)

    def _load_beliefs(self, session_id: str) -> list[Belief]:
        """Return the Brain's derived view of canonical durable user memory.

        `BrainStateStore.beliefs` is deliberately not read here as an authority.
        Durable user memory belongs to `app.knowledge.memory.Memory`; the session belief
        rows are only a per-session projection used by Brain inference and diagnostics.
        """
        try:
            rows = self.memory.profile(limit=150)
        except Exception:
            rows = []
        result: list[Belief] = []
        for row in rows:
            predicate = str(row.get('key') or '').strip()
            value = row.get('value')
            if not predicate or value is None:
                continue
            result.append(Belief(
                subject='user', predicate=predicate, value=value,
                confidence=float(row.get('confidence', 1.0) or 1.0),
                source='canonical_memory', provenance='memory-projection',
                created_at=str(row.get('updated_at') or ''),
                updated_at=str(row.get('updated_at') or ''),
                revision=int(row.get('revision', 1) or 1), status='active', supersedes='',
            ))
        return result

    def _sync_legacy_fact(self, session_id: str, predicate: str) -> Any:
        """Compatibility name for projecting a canonical Memory fact into Brain state.

        The read authority is always `Memory`; `BrainStateStore` receives only a derived copy.
        """
        try:
            key = self.memory.canonical_key(predicate)
            value = self.memory.get_fact(key)
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

            top_intent = parsed.intent_candidates[0].name if parsed.intent_candidates else ''
            operation = str(top_intent or fallback_frame.requested_operation or '').strip()
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
                        [str(x) for x in (parsed.ambiguity_reasons or ())]
                    )),
                )
                # Declarative user facts are not ambiguous goals. The semantic parser has
                # already grounded them into a concrete memory operation + predicate/value.
                if operation == 'remember' and frame.slot('predicate') and frame.slot('value'):
                    frame = SemanticFrame(
                        text=frame.text, language=frame.language, speech_act='statement',
                        concepts=tuple(sorted(set(frame.concepts) | {'memory'})),
                        entities=frame.entities, requested_operation='remember',
                        object_text=frame.object_text, slots=frame.slots,
                        question_type=frame.question_type, temporal=frame.temporal,
                        conditions=frame.conditions, uncertainty=(),
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
        # Exact durable fact retrieval for high-value first-person queries.
        if frame.requested_operation == 'query_identity':
            key = 'name'
            value = self.memory.get_fact(key)
            if value is not None:
                self._sync_legacy_fact(state.session_id or '', key)
                state.beliefs = self._load_beliefs(state.session_id or '')
                matching = [b for b in state.beliefs if b.predicate == key and b.status == 'active']
                state.evidence = rank_beliefs([b.to_dict() for b in matching], key, limit=4)
        elif frame.requested_operation == 'query_memory':
            key = frame.slot('key') or frame.slot('predicate')
            if key:
                key = self.memory.canonical_key(key)
                value = self.memory.get_fact(key)
                if value is not None:
                    self._sync_legacy_fact(state.session_id or '', key)
                    state.beliefs = self._load_beliefs(state.session_id or '')
                    matching = [b for b in state.beliefs if b.predicate == key and b.status == 'active']
                    state.evidence = rank_beliefs([b.to_dict() for b in matching], key, limit=4)
                else:
                    for alias in self.memory.key_aliases(key):
                        value = self.memory.get_fact(alias)
                        if value is not None:
                            self._sync_legacy_fact(state.session_id or '', alias)
                            state.beliefs = self._load_beliefs(state.session_id or '')
                            matching = [b for b in state.beliefs if b.predicate == alias and b.status == 'active']
                            state.evidence = rank_beliefs([b.to_dict() for b in matching], alias, limit=4)
                            break
            else:
                profile = self.memory.profile(limit=24)
                for item in profile:
                    predicate = str(item.get('key') or '').strip()
                    value = item.get('value')
                    if not predicate or value is None or not state.session_id:
                        continue
                    try:
                        self.state_store.upsert_belief(
                            session_id=state.session_id, subject='user', predicate=predicate, value=value,
                            confidence=float(item.get('confidence', 0.9) or 0.9), source='canonical_memory',
                            provenance='memory-projection',
                        )
                    except Exception:
                        continue
                state.beliefs = self._load_beliefs(state.session_id or '')
                state.evidence = rank_beliefs([b.to_dict() for b in state.beliefs], '', limit=8)
        elif frame.requested_operation == 'query_knowledge':
            query = frame.slot('query') or frame.text
            state.evidence = rank_beliefs([b.to_dict() for b in state.beliefs], query, limit=8)
            if not state.evidence:
                legacy = []
                # Search the original question and ontology aliases. This is deliberately
                # deterministic and lets Arabic/English labels reach the same stored fact.
                queries = [query]
                if 'اجتماع' in query or 'الاجتماع' in query:
                    queries += ['meeting', 'appointment']
                if 'اسم' in query:
                    queries += ['name']
                for candidate_query in dict.fromkeys(queries):
                    try:
                        legacy = self.memory.search_memory(candidate_query, top_k=8, kinds={'fact', 'preference', 'profile', 'goal', 'note'})
                    except Exception:
                        legacy = []
                    if legacy:
                        break
                if legacy:
                    state.evidence = [
                        Evidence('legacy_memory',
                                 f"{item.get('key') or item.get('kind') or 'memory'} = {item.get('value') or item.get('text') or item.get('summary') or item.get('message') or item}",
                                 'legacy_memory', float(item.get('confidence', 0.9) or 0.9), str(item.get('id') or item.get('key') or ''))
                        for item in legacy[:8]
                    ]
            state.event('evidence_requirement', source='memory_or_external', query=query, local_hits=len(state.evidence))
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
        state.event('goal_formed', objective=state.goal.objective, name=state.goal.name, query=state.goal.query)
        self.state_store.append_event(state.session_id or '', 'goal_formed', {
            'topic': state.goal.name, 'objective': state.goal.objective, 'query': state.goal.query,
            'source': 'structured_goal' if goal_override else 'natural_language',
        })
        state.beliefs = self._load_beliefs(state.session_id or '')
        if state.semantic and state.semantic.requested_operation in {'query_identity', 'query_memory'} and not state.evidence:
            query = state.semantic.slot('query') or state.goal.query or 'name'
            state.evidence = rank_beliefs([b.to_dict() for b in state.beliefs], query, limit=8)
        state.plan = plan(
            state.goal, state.semantic, state.candidates,
            state=state, experiences=self.experiences,
            learning=self.learning, registry=self.registry,
        ) if state.semantic else []
        state.event('planning', plan=[x.to_dict() for x in state.plan])
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

    def _resolve_action_args(self, action: PlannedAction, outputs: dict[str, Any]) -> dict[str, Any]:
        def resolve(value: Any) -> Any:
            if isinstance(value, str):
                for step_id, output in outputs.items():
                    token = '{{' + step_id + '}}'
                    if token in value:
                        return value.replace(token, str(output))
                return value
            if isinstance(value, dict):
                return {k: resolve(v) for k, v in value.items()}
            if isinstance(value, list):
                return [resolve(v) for v in value]
            return value
        return resolve(action.args)

    def _run_action(self, state: CognitiveState, action: PlannedAction, outputs: dict[str, Any],
                    approve: Callable[[str, dict[str, Any]], bool]) -> tuple[bool, Any, str | None, bool, float]:
        tool = self.registry.get(action.tool)
        if tool is None:
            return False, None, f'الأداة {action.tool} غير مسجلة.', False, 0.0
        args = self._resolve_action_args(action, outputs)
        errors = tool.validate_args(args)
        if errors:
            return False, None, '; '.join(errors), False, 0.0
        policy = check_tool(tool, args)
        state.event('policy_check', step=action.step_id, tool=tool.name,
                    allowed=policy.allowed, approval_required=policy.approval_required, reason=policy.reason)
        if not policy.allowed:
            return False, None, policy.reason or 'operation blocked by runtime policy', False, 0.0
        if policy.approval_required and not approve(tool.name, args):
            return False, None, 'تم رفض العملية التي تحتاج موافقة.', False, 0.0
        started = time.monotonic()
        result = tool.run(**args)
        elapsed = time.monotonic() - started
        verified, verification_error = verify_step(tool, args, result)
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

    def _execute_result(self, result: BrainResult, *, approve: Callable[[str, dict[str, Any]], bool] | None = None,
                        max_steps: int = 8, execution_guard: Callable[[], bool] | None = None) -> BrainResult:
        state = result.state
        if not state.decision or state.decision.kind not in {'execute', 'research'}:
            if state.decision and state.decision.kind == 'retrieve' and state.semantic:
                state.evidence = rank_beliefs([b.to_dict() for b in state.beliefs], state.semantic.slot('query') or state.semantic.text, limit=8)
                state.decision = deliberate(state)
                response = compose(state.decision, state)
                return BrainResult(state, response, status='completed', run_id=result.run_id)
            return BrainResult(state, result.response, result.runtime_state, status='completed', run_id=result.run_id)

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

        while pending:
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
            action = pending.pop(0)
            if any(dep not in outputs for dep in action.depends_on):
                status = 'failed'
                final = f'توقفت لأن خطوة {action.step_id} تعتمد على نتيجة لم تتوفر.'
                state.event('plan_invariant_violation', step=action.step_id, depends_on=list(action.depends_on))
                break
            tool = self.registry.get(action.tool)
            resolved_args = self._resolve_action_args(action, outputs)
            state_before = state.to_canonical_state().fingerprint()
            action_spec = self._action_spec(action, tool, resolved_args) if tool else None
            exploration_event_id = self._record_exploration_selection(state, action, result.run_id)
            prediction = None
            if action_spec is not None:
                try:
                    prediction = self.learning.transition_model.predict(state_before, action_spec.to_dict())
                except Exception:
                    prediction = None
            ok, output, error, executed_action, duration = self._run_action(state, action, outputs, approver)
            if execution_guard is not None:
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
                self._complete_exploration_event(state, exploration_event_id, executed=executed_action, ok=False, verified=False, reward=0.0)
                if executed_action:
                    state.observations.append({
                        'step_id': action.step_id, 'tool': action.tool, 'ok': False,
                        'error': str(error or 'execution failed'), 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    })
                    state.world_facts[f'action_failed:{action.tool}'] = True
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
                state.observations.append({
                    'step_id': action.step_id, 'tool': action.tool, 'ok': False,
                    'error': str(error or 'execution failed'), 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                }) if not executed_action else None
                failed_tools.add(action.tool)
                state.world_facts[f'action_failed:{action.tool}'] = True
                # Replan from observed state, but never bypass an explicit approval denial.
                if error and 'تم رفض' not in str(error):
                    candidates = discover_candidates(state.semantic, self.registry) if state.semantic else []
                    replacement = replan(state.goal, state.semantic, candidates, state=state, experiences=self.experiences,
                                         failed_tool=action.tool, learning=self.learning, registry=self.registry) if state.goal and state.semantic else []
                    if replacement:
                        replans += 1
                        self._learning_replans = replans
                        state.plan = replacement
                        state.event('replan', failed_tool=action.tool, reason='observed_failure',
                                    new_plan=[x.to_dict() for x in replacement], replan_count=replans)
                        # A replan may contain already-satisfied steps; planner removes them from state.
                        pending = replacement + pending
                        continue
                status = 'failed'
                final = f'التنفيذ توقف: {error}'
                break
            if not self._verify_output(action, output):
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
                status = 'failed'
                final = f'نفذت {action.tool} لكن التحقق من النتيجة لم ينجح.'
                state.event('verification_failed', step=action.step_id, tool=action.tool)
                break
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
                                'duration_ms': duration * 1000.0, 'attempt': 1, 'output_summary': self._safe_learning_output(output)},
                    'verified': True,
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'metadata': (('step_id', action.step_id),),
                })
            state.event('step_completed', step=action.step_id, tool=action.tool, executed_steps=executed, replans=replans)

            if action.exploration_mode and executed < max_steps:
                replacement = self._replan_after_exploration(state, explored_tool=action.tool)
                if replacement:
                    replans += 1
                    self._learning_replans = replans
                    state.plan = replacement
                    state.event('exploration_replan', explored_tool=action.tool, mode=action.exploration_mode,
                                information_gain=action.information_gain, new_plan=[x.to_dict() for x in replacement])
                    pending = replacement + pending
                    continue

        state.event('post_action_evaluation', outputs={k: str(v)[:500] for k, v in outputs.items()},
                    executed_steps=executed, replans=replans)
        if status == 'completed':
            final = compose_action_result(state, action=action if 'action' in locals() else None, output=output if 'output' in locals() else None, all_outputs=outputs)
            verified = True
            reward = 1.0
        else:
            verified = False
            reward = 0.0
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
        return BrainResult(state, final, runtime_state={'outputs': outputs, 'executed_steps': executed, 'status': status, 'replans': replans}, status=status, run_id=result.run_id)

    def act(self, user_text: str, *, approve: Callable[[str, dict[str, Any]], bool] | None = None,
            session_id: str | None = None, max_steps: int = 8, execution_guard: Callable[[], bool] | None = None) -> BrainResult:
        sid = session_id or uuid.uuid4().hex
        memory_token = push_memory(self.memory)
        try:
            result = self.think(user_text, session_id=sid)
            return self._execute_result(result, approve=approve, max_steps=max_steps, execution_guard=execution_guard)
        finally:
            pop_memory(memory_token)

    def act_structured(self, payload: dict[str, Any] | GoalSpec, *,
                       approve: Callable[[str, dict[str, Any]], bool] | None = None,
                       session_id: str | None = None, max_steps: int = 8, execution_guard: Callable[[], bool] | None = None) -> BrainResult:
        memory_token = push_memory(self.memory)
        try:
            result = self.think_structured(payload, session_id=session_id)
            return self._execute_result(result, approve=approve, max_steps=max_steps, execution_guard=execution_guard)
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
            # Deletion is authoritative in Memory; immediately refresh the derived Brain view so
            # the returned state cannot expose a belief that was just deleted.
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

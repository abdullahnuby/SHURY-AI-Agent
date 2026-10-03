from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from app.brain.methods import MethodRegistry
from app.brain.models import CandidateAction, CognitiveState, GoalSpec, PlannedAction
from app.learning.exploration import build_exploration_actions
from app.learning.diagnosis import task_signature
from app.learning.meta_strategy import MetaStrategyController


METHODS = MethodRegistry()


def make_goal(frame: Any) -> GoalSpec:
    op = frame.requested_operation
    q = frame.slot('query')
    if op.startswith('query_'):
        name = op
        desired = (f'answer_available:{op}',)
    elif op == 'remember':
        name = 'maintain_memory'
        desired = (f'belief:{frame.slot("predicate")}',)
    elif op == 'forget_memory':
        name = 'forget_memory'
        desired = ('fact_deleted',)
    elif op == 'calculate':
        name = 'perform_calculation'
        desired = ('calculation_completed',)
    elif op == 'compound_calculate_remember':
        name = 'perform_and_persist_calculation'
        desired = ('calculation_completed', 'fact_saved')
    elif op in {'research', 'learning_intent', 'open_world_learning'}:
        name = 'ground_research_question' if op == 'research' else 'self_improvement_research'
        desired = ('answer_grounded',) if op == 'research' else ('research_evidence', 'learning_candidate')
    elif op == 'skill_query':
        name = 'inspect_skills'
        desired = ('skills_observed', 'skill_candidates_observed')
    else:
        name = op or 'open_task'
        desired = ()
    return GoalSpec(
        name=name,
        objective=frame.text,
        desired_state=desired,
        constraints=tuple(frame.conditions) + tuple(f'temporal:{x}' for x in frame.temporal),
        success_conditions=desired,
        query=q,
        required_evidence=('memory',) if name in {'query_identity', 'query_memory'} else (),
    )


def _experience_adjustment(experiences: Any, operation: str, tool: str) -> float:
    if experiences is None:
        return 0.0
    try:
        methods = experiences.successful_methods(operation, limit=24)
    except Exception:
        return 0.0
    for item in methods:
        if item.get('tool') != tool:
            continue
        uses = max(1, int(item.get('uses') or 0))
        reward = float(item.get('reward') or 0.0)
        # Bounded, evidence-weighted boost. One success never dominates the base cost.
        return min(1.5, 0.25 * (reward * (uses / (uses + 2))))
    return 0.0


def _learning_adjusted_candidates(candidates: list[CandidateAction], operation: str, experiences: Any) -> list[CandidateAction]:
    if experiences is None or not candidates:
        return list(candidates)
    try:
        rows = experiences.by_tool(limit=250)
    except Exception:
        return list(candidates)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if str(row.get('operation') or '') != operation:
            continue
        grouped.setdefault(str(row.get('tool') or ''), []).append(row)
    adjusted: list[CandidateAction] = []
    for candidate in candidates:
        history = grouped.get(candidate.tool, [])
        boost = 0.0
        if history:
            verified = sum(1 for row in history if row.get('verified'))
            attempts = len(history)
            reward = sum(float(row.get('reward') or 0.0) for row in history) / attempts
            # Small positive reinforcement for verified success; explicit penalty for
            # repeatedly unreliable tools. The prior never overwhelms semantic fit.
            boost = min(0.8, 0.12 * verified + 0.25 * reward)
            if attempts >= 3 and verified / attempts < 0.5:
                boost -= 0.9
        self_adjustment = 0.0
        try:
            self_adjustment = float(experiences.self_model_action_assessment(
                tool=candidate.tool, capability=candidate.capability, context_signature=task_signature(operation) if operation else ''
            ).get('adjustment', 0.0) or 0.0)
        except Exception:
            self_adjustment = 0.0
        combined = max(-1.20, min(1.00, boost + self_adjustment))
        reason = (candidate.reason + ',experience-prior' if abs(boost) > 1e-9 else candidate.reason)
        if abs(self_adjustment) > 1e-9:
            reason += f',self-model({self_adjustment:+.2f})'
        adjusted.append(replace(candidate, score=candidate.score + combined, reason=reason.strip(',')))
    adjusted.sort(key=lambda x: (-x.score, x.cost, x.tool))
    return adjusted


def _method_score(method: Any, steps: list[PlannedAction], operation: str, experiences: Any) -> float:
    if not steps:
        return float('-inf')
    total_cost = sum(_step_cost(step) for step in steps)
    learned = sum(_experience_adjustment(experiences, operation, step.tool) for step in steps)
    return float(method.priority) + learned - (0.12 * total_cost) - (0.03 * max(0, len(steps) - 1))


_EXTERNAL_WEB_TOOLS = {'research_and_learn', 'web_research', 'internet_research'}


def _source_allowed_tools(frame: Any) -> set[str] | None:
    if not _requires_external_web(frame):
        return None
    concepts = {str(x) for x in (getattr(frame, 'concepts', ()) or ())}
    if concepts & {'learning', 'open_world_learning', 'learning_intent'}:
        # The user asked to LEARN from the web; route through the open-world learning
        # operator rather than a plain retrieval tool. This keeps the intended outcome
        # (evidence + indexed knowledge + declarative learning candidate) intact.
        return {'research_and_learn'}
    return {'web_research', 'internet_research'}
_EXTERNAL_MARKERS = (
    'from web', 'from the web', 'from internet', 'from the internet',
    'search online', 'search the internet', 'on the web', 'on the internet',
    'الويب', 'الإنترنت', 'الانترنت', 'اونلاين', 'أونلاين',
)


def _requires_external_web(frame: Any) -> bool:
    text = str(getattr(frame, 'text', '') or '').casefold()
    return any(marker in text for marker in _EXTERNAL_MARKERS)


def _model_plan_respects_source(frame: Any, steps: list[PlannedAction]) -> bool:
    allowed = _source_allowed_tools(frame)
    if allowed is None:
        return True
    return bool(steps) and all(step.tool in allowed for step in steps)


def _step_cost(step: PlannedAction) -> float:
    # Method planning only sees the action contract; actual runtime cost is resolved later.
    return 1.0 + (0.15 if 'remember' in step.capability else 0.0)


def _satisfied(step: PlannedAction, state_facts: dict[str, Any]) -> bool:
    if not step.expected_effects:
        return False
    return all(effect in state_facts for effect in step.expected_effects)


def _normalize_plan(plan: list[PlannedAction], state_facts: dict[str, Any], *, prefix: str = 's') -> list[PlannedAction]:
    out: list[PlannedAction] = []
    completed_ids: set[str] = set()
    for step in plan:
        if _satisfied(step, state_facts):
            completed_ids.add(step.step_id)
            continue
        deps = tuple(dep for dep in step.depends_on if dep not in completed_ids)
        out.append(PlannedAction(
            step_id=step.step_id,
            capability=step.capability,
            tool=step.tool,
            args=step.args,
            depends_on=deps,
            expected_effects=step.expected_effects,
            rationale=step.rationale,
        ))
    return out


def _model_plan_to_brain_plan(model_plan, registry: dict[str, Any]) -> list[PlannedAction]:
    """Adapt the canonical domain Plan back into the Brain's PlannedAction contract."""
    out: list[PlannedAction] = []
    for step in getattr(model_plan, 'steps', ()):
        tool = registry.get(step.tool)
        if tool is None:
            return []
        out.append(PlannedAction(
            step_id=str(step.id),
            capability=str(getattr(tool, 'capability', None) or step.tool),
            tool=str(step.tool),
            args=dict(step.args or {}),
            depends_on=tuple(step.depends_on or ()),
            expected_effects=tuple(getattr(tool, 'produces', ()) or ()),
            rationale='model-based search: learned transition + value + uncertainty + verified certificate',
        ))
    return out


def _try_model_based_plan(goal: GoalSpec, state: CognitiveState, registry: dict[str, Any], learning: Any) -> list[PlannedAction]:
    """Use Phase-7 search as the default planning strategy when learned evidence exists.

    It is a strategy inside the existing Brain planner, not a second execution authority.
    A missing/insufficient learned graph simply falls back to the deterministic method planner.
    """
    if learning is None or state is None or not registry:
        return []
    try:
        state_signature = state.to_canonical_state().fingerprint()
        if not state_signature:
            return []
        model = learning.transition_model
        if not model.actions_for_state(state_signature, limit=1):
            return []
        from app.planning.model_based_planner import ModelBasedPlanner
        learned = ModelBasedPlanner(
            model,
            learning.value_model,
            registry=registry,
            max_depth=max(1, min(5, len(state.plan) or 5)),
        ).plan(
            goal.objective,
            state_signature,
            initial_facts=set(state.world_facts) | {str(c.name) for c in state.capabilities},
            initial_resources={},
        )
        if not learned.steps:
            return []
        return _model_plan_to_brain_plan(learned, registry)
    except Exception:
        return []


def _try_exploration_plan(
    goal: GoalSpec,
    frame: Any,
    state: CognitiveState | None,
    deterministic_plan: list[PlannedAction],
    registry: dict[str, Any],
    learning: Any,
    avoid_tools: set[str] | None = None,
    allow_exploration: bool = True,
) -> list[PlannedAction]:
    """Select a safe information action when the current plan lacks evidence.

    This is the missing Phase-8 bridge: previously ExplorationPolicy existed as a library,
    but the primary Brain never gave it a chance to propose an action that semantic planning
    had not already enumerated. Unknown actions are now admitted only through explicit
    exploration-safe tool contracts with deterministic argument grounding.
    """
    if learning is None or state is None or frame is None or not registry:
        return []
    # Exploration must not bypass mandatory semantic slots. In particular, a bare
    # `learn` request has no topic yet; probing the research store for the literal word
    # `learn` is not intelligent behavior and can create an apparent plan while the
    # deliberator correctly asks for clarification.
    mandatory_uncertainties = {
        'learning_topic_required',
        'capability_not_identified',
    }
    if mandatory_uncertainties.intersection(set(getattr(frame, 'uncertainty', ()) or ())):
        return []
    if not hasattr(learning, 'exploration_policy'):
        return []
    try:
        state_signature = state.to_canonical_state().fingerprint()
        if not state_signature:
            return []
        goal_text = goal.objective or frame.text
        seed: list[Any] = []
        for step in deterministic_plan[:1]:
            seed.append({
                'capability': step.capability,
                'tool': step.tool,
                'parameters': dict(step.args or {}),
                'preconditions': tuple(getattr(registry.get(step.tool), 'preconditions', ()) or ()),
                'expected_effects': tuple(step.expected_effects or ()),
                'risk': str(getattr(registry.get(step.tool), 'risk', 'low')),
                'reversible': bool(getattr(registry.get(step.tool), 'reversible', False)),
            })
        allowed_source_tools = _source_allowed_tools(frame)
        actions = [action for action in build_exploration_actions(goal_text, registry, seed_actions=seed)
                   if str(action.get("tool") or "") not in set(avoid_tools or ())
                   and (allowed_source_tools is None or str(action.get("tool") or "") in allowed_source_tools)]
        if not actions:
            return []
        decision = learning.exploration_policy.decide(state_signature, goal_text, actions, registry)
        if decision is None:
            return []
        state.event('exploration_decision', **decision.to_dict())

        if decision.mode not in {'information', 'explore', 'relearn'}:
            return []
        if float(decision.goal_alignment) < 0.45:
            return []
        if decision.mode != 'relearn' and float(decision.information_gain) < 0.55:
            return []
        if decision.selected_tool in {step.tool for step in deterministic_plan[:1]}:
            # The primary plan already performs the chosen information action. Do not
            # add a second identical step merely because the exploration policy scored it.
            return []

        direct_uncertain = not deterministic_plan
        if deterministic_plan:
            direct = deterministic_plan[0]
            try:
                prediction = learning.transition_model.predict(
                    state_signature,
                    {
                        'capability': direct.capability,
                        'tool': direct.tool,
                        'parameters': dict(direct.args or {}),
                        'preconditions': tuple(getattr(registry.get(direct.tool), 'preconditions', ()) or ()),
                        'expected_effects': tuple(direct.expected_effects or ()),
                        'risk': str(getattr(registry.get(direct.tool), 'risk', 'low')),
                        'reversible': bool(getattr(registry.get(direct.tool), 'reversible', False)),
                    },
                )
                direct_uncertain = prediction is None or float(prediction.uncertainty) >= 0.55 or int(prediction.evidence_count) < 3
            except Exception:
                direct_uncertain = True
        if not direct_uncertain and decision.mode != 'relearn':
            return []

        tool = registry.get(decision.selected_tool or '')
        action = decision.selected_action or {}
        if tool is None:
            return []
        return [PlannedAction(
            step_id='explore-1',
            capability=str(getattr(tool, 'capability', None) or decision.selected_tool),
            tool=str(decision.selected_tool),
            args=dict(action.get('parameters') or {}),
            depends_on=(),
            expected_effects=tuple(getattr(tool, 'produces', ()) or ()),
            rationale=f'Phase-8 {decision.mode}: {decision.reason}',
            exploration_mode=decision.mode,
            information_gain=float(decision.information_gain),
            exploration_reason=decision.reason,
        )]
    except Exception:
        return []


def plan(goal: GoalSpec, frame: Any, candidates: list[CandidateAction], *,
         state: CognitiveState | None = None, experiences: Any | None = None,
         avoid_tools: set[str] | None = None, learning: Any | None = None,
         registry: dict[str, Any] | None = None, allow_exploration: bool = True) -> list[PlannedAction]:
    """Choose a procedural method using capability contracts and prior verified outcomes."""
    if frame is None:
        return []
    avoid = set(avoid_tools or ())
    mandatory_uncertainties = {'learning_topic_required', 'capability_not_identified'}
    if mandatory_uncertainties.intersection(set(getattr(frame, 'uncertainty', ()) or ())):
        return []
    filtered = [c for c in candidates if c.tool not in avoid]
    allowed_source_tools = _source_allowed_tools(frame)
    if allowed_source_tools is not None:
        filtered = [c for c in filtered if c.tool in allowed_source_tools]
    filtered = _learning_adjusted_candidates(filtered, frame.requested_operation, experiences)
    operation = frame.requested_operation

    # Meta-strategy is a persistent route controller for the canonical Brain planner.
    # It never selects concrete tools; it only determines which already-governed
    # planning family gets first consideration for this state type.
    meta_decision = None
    if learning is not None:
        try:
            meta_controller = getattr(learning, "meta_strategy", None)
            if meta_controller is None and hasattr(getattr(learning, "store", None), "meta_strategy_observation"):
                meta_controller = MetaStrategyController(learning.store)
            if meta_controller is not None:
                if getattr(frame, "conditions", None):
                    state_type = "conditional"
                elif operation.startswith("compound_") or len(getattr(goal, "desired_state", ()) or ()) > 1:
                    state_type = "compound"
                else:
                    state_type = "atomic"
                available = ["direct", "search", "verification-first"]
                if state_type == "compound":
                    available.insert(1, "sequential")
                if hasattr(learning, "exploration_policy"):
                    available.extend(["information-first", "exploration"])
                if getattr(state, "trace", None) and any(e.get("kind") == "action_observed" and not e.get("ok") for e in state.trace):
                    available.append("recovery-first")
                meta_decision = meta_controller.recommend(state_type, available=available, context={"operation": operation})
        except Exception:
            meta_decision = None

    options: list[tuple[float, str, list[PlannedAction]]] = []
    facts = dict(state.world_facts) if state is not None else {}
    for method in METHODS.for_operation(operation):
        steps = method.build(frame, filtered)
        if not steps:
            continue
        # Contracts are checked before an action can be considered executable.
        invalid = False
        for step in steps:
            candidate = next((c for c in filtered if c.tool == step.tool), None)
            if candidate is None:
                invalid = True
                break
            if not all(isinstance(effect, str) and effect for effect in candidate.effects):
                invalid = True
                break
        if invalid:
            continue
        score = _method_score(method, steps, operation, experiences)
        options.append((score, method.name, _normalize_plan(steps, facts)))
    options = [x for x in options if x[2]]
    options.sort(key=lambda item: (-item[0], item[1]))
    deterministic_plan = options[0][2] if options else []
    meta_evidence_count = int(getattr(meta_decision, "evidence_count", 0) or 0) if meta_decision else 0
    selected_strategy = (str(getattr(meta_decision, "preferred_strategy", "") or "direct")
                         if meta_decision and meta_evidence_count > 0 else "")
    # The pending action topology is part of the execution state used by Phase 1→7
    # transition fingerprints. During planning, state.plan has not yet been assigned by
    # the kernel, so materialize the deterministic candidate before asking the learned
    # planner for a model-based alternative. This makes the planning fingerprint identical
    # to the state fingerprint captured immediately before real execution.
    if state is not None:
        state.plan = list(deterministic_plan)
    # Route selection is explicit and inspectable. The selected strategy only chooses
    # the planning family; normal candidate contracts, validation and runtime policy
    # still govern every resulting action.
    if selected_strategy in {"direct", "sequential", "verification-first", "recovery-first", "information-first", "exploration"}:
        deterministic_or_learned = deterministic_plan
    else:
        deterministic_or_learned = deterministic_plan

    model_based = None
    if selected_strategy == "search":
        model_based = _try_model_based_plan(goal, state, registry or {}, learning)
    elif not selected_strategy:
        # Cold-start behavior intentionally preserves the pre-controller V8/V9 route:
        # a learned model may be used when available, and the exploration policy may still
        # request an information action. The meta table starts learning only after evidence.
        model_based = _try_model_based_plan(goal, state, registry or {}, learning)

    if model_based and _model_plan_respects_source(frame, model_based):
        deterministic_or_learned = model_based

    if state is not None and meta_decision is not None:
        state.event("meta_strategy_route", state_type=meta_decision.state_type,
                    strategy=selected_strategy or str(getattr(meta_decision, "preferred_strategy", "direct") or "direct"),
                    applied=bool(selected_strategy), evidence_count=meta_decision.evidence_count,
                    alternatives=list(meta_decision.alternatives))

    exploration_first = selected_strategy in {"information-first", "exploration"} or not selected_strategy
    # Canonical memory queries are direct authority reads. Exploration must never replace
    # a typed memory route with research merely because the learning policy wants more
    # information; this preserves the Memory authority established in Phase 7.
    exploration_allowed = allow_exploration and operation not in {"query_identity", "query_memory"}
    exploratory = _try_exploration_plan(
        goal, frame, state, deterministic_or_learned, registry or {}, learning, avoid_tools=avoid
    ) if exploration_allowed and exploration_first else []
    if exploratory:
        if meta_decision:
            exploratory[0] = replace(exploratory[0], rationale=f"meta-strategy={selected_strategy}; {exploratory[0].rationale}")
        return exploratory

    # Carry the decision on the plan-facing actions so runtime/learning can identify
    # the exact strategy route that was attempted. This is metadata only; authority
    # remains in validation, policy and execution.
    if deterministic_or_learned and meta_decision is not None:
        deterministic_or_learned = [
            replace(planned, rationale=f"meta-strategy={selected_strategy}; {planned.rationale}")
            for planned in deterministic_or_learned
        ]
    return deterministic_or_learned


def replan(goal: GoalSpec, frame: Any, candidates: list[CandidateAction], *,
           state: CognitiveState, experiences: Any | None = None,
           failed_tool: str | None = None, learning: Any | None = None,
           registry: dict[str, Any] | None = None, avoid_tools: set[str] | None = None,
           allow_exploration: bool = True) -> list[PlannedAction]:
    """Recompute the unsatisfied suffix after an observed failure/state change."""
    return plan(
        goal,
        frame,
        candidates,
        state=state,
        experiences=experiences,
        avoid_tools=(set(avoid_tools or ()) | ({failed_tool} if failed_tool else set())),
        learning=learning,
        registry=registry,
        allow_exploration=allow_exploration,
    )

"""Personal Agent V11 runtime.

Model-free long-horizon runtime:
understand -> plan/search -> validate/policy -> dependency-safe execute
(possibly parallel) -> verify -> transition world -> checkpoint/effect ->
replan/resume -> learn verified experience.
"""
import json
import os
import time
import inspect
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from app.knowledge.memory import get_memory
from app.domain.plan import validate, resolve, Plan
from app.planning.planner import RulePlanner, Planner
from app.runtime.registry import load_tools
from app.domain.state import AgentState
from app.runtime.policy import check_tool
from app.runtime.session_context import push_session, pop_session
from app.runtime.verify import verify_step
from app.runtime.verification import verify_objective
from app.intelligence.understanding import understand, normalize
from app.intelligence.semantic import semantic_understand, SemanticContract
from app.planning.decision import decide
from app.domain.context import resolve_goal
from app.domain.world import WorldState, StateDelta
from app.world.model import WorldModel
from app.world.store import load_session_world, save_session_world
from app.planning.replanner import assess_failure
from app.planning.repair import repair_suffix
from app.planning.adaptive_execution import AdaptiveExecutionController
from app.skills.registry import SkillBank
from app.skills.compiler import compile_verified_run
from app.learning.manager import SelfImprovementManager
from app.intelligence.task_compiler import compile_task_ir
from app.runtime.response import compose_final_response
from app.production.redaction import redact

LOG_FILE = Path(__file__).resolve().parents[1] / "logs" / "agent.jsonl"
TERMINAL = {"cancelled", "blocked", "failed", "completed", "needs_user", "max_steps", "timeout"}


def _audit(event: dict, trace_id: str | None = None, run_id: str | None = None):
    LOG_FILE.parent.mkdir(exist_ok=True)
    payload = redact(dict(event))
    payload["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if trace_id:
        payload["trace_id"] = trace_id
    if run_id:
        payload["run_id"] = run_id
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _stop(state: AgentState, status: str, msg: str):
    if state.plan:
        for s in state.plan.steps:
            if s.status == "pending":
                s.status = "skipped"
    state.status, state.final_message = status, msg


def _checkpoint(state: AgentState, mem, status: str | None = None):
    if not state.plan:
        return
    current = status or state.status
    pending = [i for i, s in enumerate(state.plan.steps) if s.status == "pending"]
    state.next_index = pending[0] if pending else len(state.plan.steps)
    mem.checkpoint(
        state.run_id, state.goal, state.plan.to_dict(), state.outputs,
        state.world.snapshot(), state.next_index, current,
    )
    mem.update_run(state.run_id, current, state.plan.to_dict(), state.final_message)
    state.checkpointed = True


def _prepare_args(step, tool, outputs):
    return resolve(step.args, outputs)


def _ready_steps(plan: Plan) -> list:
    done = {s.id for s in plan.steps if s.status == "done"}
    return [s for s in plan.steps if s.status == "pending" and all(d in done for d in s.depends_on)]


def _run_attempt(step, tool, args, state_before: str, mem, run_id: str):
    last = None
    total_duration_ms = 0.0
    effect_id = None
    for attempt in range(1, tool.retries + 2):
        step.attempts = attempt
        started = time.monotonic()
        last = tool.run(**args)
        duration_ms = (time.monotonic() - started) * 1000.0
        total_duration_ms += duration_ms
        verified = False
        if last.ok:
            verified, verification_error = verify_step(tool, args, last)
            if not verified:
                last.ok = False
                last.error = verification_error
        mem.record_tool_outcome(tool.name, bool(last.ok and verified))
        effect_id = mem.record_effect(
            run_id=run_id, step_id=step.id, attempt=attempt, tool=tool.name,
            args=args, output=last.data, ok=bool(last.ok), verified=verified,
            error=last.error, duration_ms=duration_ms, state_before=state_before,
        )
        mem.record_event("tool_observation", {
            "run_id": run_id, "step": step.id, "tool": tool.name,
            "attempt": attempt, "ok": last.ok, "verified": verified,
            "duration_ms": round(duration_ms, 3), "error": last.error,
        })
        if last.ok:
            return last, verified, duration_ms, effect_id
    return last, False, total_duration_ms, effect_id


def _apply_success(state: AgentState, step, tool, result, duration: float, effect_id: int, mem, parallel: bool):
    before_snapshot = state.world.snapshot()
    before = state.world.fingerprint()
    delta = StateDelta(add=tool.produces, remove=tool.removes,
                       resource_delta=tool.resource_costs)
    # A parallel batch applies each independent effect deterministically in plan order;
    # wall-clock elapsed for the batch is accounted separately by the caller.
    state.world.transition(delta, 0.0 if parallel else duration, tool.name)
    wm = WorldModel()
    if getattr(tool, "emits_world_delta", False):
        wm.apply_structured_observation(state.world, result.data)
    after = state.world.fingerprint()
    mem.update_effect_state_after(effect_id, after)
    step.status, step.output, step.error = "done", result.data, None
    state.outputs[step.id] = result.data
    state.world.last_outputs["last_result"] = result.data
    obs = wm.observe(
        world_before=WorldState.from_snapshot(before_snapshot),
        world_after=state.world,
        tool=tool.name, ok=True, verified=True, output=result.data,
        metadata={"run_id": state.run_id, "step_id": step.id, "effect_id": effect_id},
    )
    _audit({"event": "state_transition", "step": step.id, "tool": tool.name,
            "state_before": before, "state_after": after, "observation_id": obs.observation_id,
            "state_diff": obs.state_diff.to_dict()}, state.trace_id, state.run_id)


def _execute_ready_step(state, step, registry, mem):
    tool = registry[step.tool]
    try:
        args = _prepare_args(step, tool, state.outputs)
    except Exception as e:
        return step, tool, None, False, 0.0, None, f"input resolution failed: {e}"
    errors = tool.validate_args(args)
    if errors:
        return step, tool, None, False, 0.0, None, "; ".join(errors)
    policy = check_tool(tool, args)
    _audit({"event": "policy", "step": step.id, "tool": tool.name,
            "allowed": policy.allowed, "approval_required": policy.approval_required}, state.trace_id, state.run_id)
    if not policy.allowed:
        return step, tool, None, False, 0.0, None, policy.reason
    if policy.approval_required:
        return step, tool, None, False, 0.0, None, "approval_required"
    state_before = state.world.fingerprint()
    result, verified, duration, effect_id = _run_attempt(step, tool, args, state_before, mem, state.run_id)
    if result and result.ok and verified:
        return step, tool, result, True, duration, effect_id, None
    return step, tool, result, False, duration, effect_id, (result.error if result else "unknown failure")


def _execute(state: AgentState, registry: dict, mem, approve: Callable[[str, dict], bool], max_replans: int = 2, context_goal: str | None = None):
    started_at = time.monotonic()
    adaptive = AdaptiveExecutionController(mem)
    while True:
        pending = [s for s in state.plan.steps if s.status == "pending"]
        if not pending:
            break
        done_count = sum(1 for s in state.plan.steps if s.status == "done")
        if done_count >= state.max_steps:
            _stop(state, "max_steps", "وصلت للحد الأقصى للخطوات")
            _checkpoint(state, mem, state.status)
            return
        if time.monotonic() - started_at > state.max_seconds:
            _stop(state, "timeout", "الوقت المسموح خلص")
            _checkpoint(state, mem, state.status)
            return

        ready = _ready_steps(state.plan)
        if not ready:
            _stop(state, "failed", "تعذر إيجاد خطوة جاهزة: dependency deadlock")
            _checkpoint(state, mem, state.status)
            return

        # Approval/effectful work is serialized. Independent safe work can fan out.
        approval_ready = next((s for s in ready if registry[s.tool].requires_approval), None)
        if approval_ready is not None:
            tool = registry[approval_ready.tool]
            args = _prepare_args(approval_ready, tool, state.outputs)
            policy = check_tool(tool, args)
            if not policy.allowed:
                _stop(state, "blocked", policy.reason)
                _checkpoint(state, mem, state.status)
                return
            state.status = "waiting_approval"
            state.final_message = f"مطلوب موافقة قبل {tool.name}"
            _checkpoint(state, mem, state.status)
            if not approve(tool.name, args):
                _audit({"event": "denied", "step": approval_ready.id, "tool": tool.name, "args": args}, state.trace_id, state.run_id)
                _stop(state, "cancelled", "اتلغى بناءً على رفضك")
                _checkpoint(state, mem, state.status)
                return
            state.status = "running"
            result_tuple = _execute_ready_step(state, approval_ready, registry, mem)
            step, tool, result, ok, duration, effect_id, error = result_tuple
            if error == "approval_required":
                # We already approved; execute directly to avoid double prompt.
                state_before = state.world.fingerprint()
                result, verified, duration, effect_id = _run_attempt(step, tool, args, state_before, mem, state.run_id)
                ok = bool(result and result.ok and verified)
                error = None if ok else (result.error if result else "unknown failure")
            if ok:
                _apply_success(state, step, tool, result, duration, effect_id, mem, False)
                state.status = "running"
                _checkpoint(state, mem, "running")
                continue
            step.status, step.error = "failed", error or "unknown failure"
            rp = assess_failure(step.tool, step.error, registry, step.clause_text, mem)
            if state.replans < max_replans:
                repaired_plan, repair_info = repair_suffix(state, step.id, registry, mem)
                if repaired_plan is not None and repair_info.get("reason") == "repaired":
                    old_plan = state.plan
                    state.plan = repaired_plan
                    state.replans += 1
                    mem.record_event("plan_repair", {"run_id": state.run_id, "failed_step": step.id,
                                                     "count": state.replans, "details": repair_info})
                    _audit({"event": "plan_repair", "failed_step": step.id,
                            "preserved_prefix": repair_info.get("preserved_prefix_steps")}, state.trace_id, state.run_id)
                    _checkpoint(state, mem, "running")
                    continue
            if rp.should_replan and state.replans < max_replans and rp.replacement_tool:
                old = step.tool
                step.tool = rp.replacement_tool
                step.capability = registry[step.tool].capability or step.tool
                step.status = "pending"
                step.error = None
                step.output = None
                step.attempts = 0
                state.replans += 1
                mem.record_event("replan", {"run_id": state.run_id, "step": step.id, "from_tool": old,
                                             "to_tool": step.tool, "count": state.replans})
                _checkpoint(state, mem, "running")
                continue
            _stop(state, "failed", f"الأداة {step.tool} فشلت: {step.error}")
            _checkpoint(state, mem, state.status)
            return

        # Adaptive execution policy: rank currently-ready candidates using live
        # reliability, risk, cost and estimated information value instead of blindly
        # taking plan order. This changes execution choice, not logical dependencies.
        previous_output = state.world.last_outputs.get("last_result")
        ranked_ready = []
        for candidate in ready:
            utility = adaptive.score_tool(registry[candidate.tool], information_value=(
                1.0 if previous_output is None else 0.5
            ))
            ranked_ready.append((utility, candidate))
        ranked_ready.sort(key=lambda x: (-x[0], x[1].id))
        ready = [s for _, s in ranked_ready]
        if ranked_ready:
            mem.record_event("adaptive_execution_decision", {
                "run_id": state.run_id,
                "ready": [s.tool for _, s in ranked_ready],
                "utilities": {s.id: round(u, 6) for u, s in ranked_ready},
                "selected": ranked_ready[0][1].tool,
                "rule": "reliability+cost+risk+information-value",
            })

        # Fan-out only truly independent, parallel-safe, non-approval steps.
        parallel_ready = [s for s in ready if registry[s.tool].parallel_safe and not registry[s.tool].requires_approval]
        # Enforce exclusive-resource mutexes even when tools are individually parallel-safe.
        batch = []
        used_exclusive = set()
        for candidate in parallel_ready:
            exclusive = set(registry[candidate.tool].exclusive_resources)
            if exclusive & used_exclusive:
                continue
            batch.append(candidate)
            used_exclusive.update(exclusive)
        use_parallel = len(batch) >= 2
        batch = batch if use_parallel else [ready[0]]
        remaining = state.max_steps - done_count
        batch = batch[:max(1, remaining)]

        results = []
        batch_started = time.monotonic()
        if use_parallel and len(batch) > 1:
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = [pool.submit(_execute_ready_step, state, step, registry, mem) for step in batch]
                for future in futures:
                    results.append(future.result())
        else:
            results.append(_execute_ready_step(state, batch[0], registry, mem))

        # Apply state changes in deterministic plan order, never completion order.
        results.sort(key=lambda item: state.plan.steps.index(item[0]))
        failures = []
        durations = []
        for step, tool, result, ok, duration, effect_id, error in results:
            durations.append(duration)
            if ok:
                _apply_success(state, step, tool, result, duration, effect_id, mem, use_parallel and len(results) > 1)
            else:
                step.status, step.error = "failed", error or "unknown failure"
                failures.append((step, error))
        if use_parallel and durations:
            state.world.elapsed += max(durations)

        for step, error in failures:
            try:
                from app.skills.evolution import distill_failure
                distilled = distill_failure(state.goal, step.tool, error or "unknown failure", clause=step.clause_text)
                mem.record_event("failure_skill_distilled", {
                    "run_id": state.run_id, "step": step.id, "skill_key": distilled["key"],
                    "tool": step.tool, "error_pattern": distilled["error_pattern"],
                })
            except Exception as exc:
                mem.record_event("failure_skill_distill_error", {"run_id": state.run_id, "step": step.id, "error": str(exc)})
            adaptive_decision = adaptive.after_result(
                registry[step.tool],
                type("Result", (), {"ok": False, "data": None})(),
                query=state.goal, attempts=step.attempts,
            )
            mem.record_event("adaptive_execution_outcome", {
                "run_id": state.run_id, "step": step.id, "tool": step.tool,
                "action": adaptive_decision.action, "reason": adaptive_decision.reason,
            })
            rp = assess_failure(step.tool, error, registry, step.clause_text, mem)
            _audit({"event": "replan_assessment", "step": step.id, "should_replan": rp.should_replan,
                    "reason": rp.reason, "replacement": rp.replacement_tool}, state.trace_id, state.run_id)
            if state.replans < max_replans:
                repaired_plan, repair_info = repair_suffix(state, step.id, registry, mem)
                if repaired_plan is not None and repair_info.get("reason") == "repaired":
                    state.plan = repaired_plan
                    state.replans += 1
                    mem.record_event("plan_repair", {"run_id": state.run_id, "failed_step": step.id,
                                                     "count": state.replans, "details": repair_info})
                    continue
            if rp.should_replan and state.replans < max_replans and rp.replacement_tool:
                old = step.tool
                step.tool = rp.replacement_tool
                step.capability = registry[step.tool].capability or step.tool
                step.status, step.error, step.output, step.attempts = "pending", None, None, 0
                state.replans += 1
                mem.record_event("replan", {"run_id": state.run_id, "step": step.id,
                                             "from_tool": old, "to_tool": step.tool, "count": state.replans})
            else:
                _stop(state, "failed", f"الأداة {step.tool} فشلت: {error}")
                _checkpoint(state, mem, state.status)
                return

        state.status = "running"
        _checkpoint(state, mem, "running")
        _audit({"event": "batch", "parallel": use_parallel, "steps": [s.id for s in batch],
                "wall_ms": round((time.monotonic() - batch_started) * 1000, 3)}, state.trace_id, state.run_id)

    state.status = "completed"
    state.world.last_goal = context_goal or state.goal
    if state.goal not in state.world.completed_goals:
        state.world.completed_goals.append(state.goal)
    state.final_message = " | ".join(f"{s.tool}: {s.output}" for s in state.plan.steps if s.status == "done")
    skill_key = state.plan.diagnostics.get("skill_key") if state.plan else None
    if skill_key:
        try:
            SkillBank().record_outcome(skill_key, True)
        except Exception:
            pass
    try:
        compiled = compile_verified_run(state, mem)
        if compiled:
            mem.record_event("skill_compiled", {"run_id": state.run_id, "skill_key": compiled.key,
                                                 "version": compiled.version, "status": compiled.status})
    except Exception as exc:
        mem.record_event("skill_compile_error", {"run_id": state.run_id, "error": str(exc)})
    objective = verify_objective(state.plan, state.status)
    if not objective.ok:
        state.status, state.final_message = "failed", objective.reason
        state.world.failed_goals.append(state.goal)
    _checkpoint(state, mem, state.status)


def _prepare_run(state: AgentState, mem, session_id: str | None = None):
    mem.start_run(state.run_id, state.trace_id, state.goal, state.plan.to_dict() if state.plan else None, session_id=session_id)
    _checkpoint(state, mem, "running")


def _call_planner(planner, goal, mem, world, task_ir=None, learning=None, registry=None):
    method = planner.plan
    try:
        signature = inspect.signature(method)
        params = list(signature.parameters.values())
        names = {p.name for p in params}
    except (TypeError, ValueError):
        params, names = [], set()
    accepts_world = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params) or len(params) >= 3
    kwargs = {}
    if "task_ir" in names:
        kwargs["task_ir"] = task_ir
    if "learning" in names:
        kwargs["learning"] = learning
    if "registry" in names:
        kwargs["registry"] = registry
    if kwargs:
        if accepts_world:
            return method(goal, mem, world, **kwargs)
        return method(goal, mem, **kwargs)
    if accepts_world:
        return method(goal, mem, world)
    return method(goal, mem)


def run_agent(goal: str, approve: Callable[[str, dict], bool] = lambda t, a: True,
              max_steps: int = 6, max_seconds: float = 30.0,
              planner: Planner | None = None, max_replans: int = 2,
              resources: dict[str, float] | None = None, session_id: str | None = None) -> AgentState:
    planner = planner or RulePlanner()
    session_token = push_session(session_id)
    registry, mem = load_tools(), get_memory()
    learning = SelfImprovementManager()
    state = AgentState(goal=goal, max_steps=max_steps, max_seconds=max_seconds, status="running")
    _audit({"event": "goal", "goal": goal}, state.trace_id, state.run_id)

    world = load_session_world(mem, session_id)
    if resources:
        world.resources.update({k: float(v) for k, v in resources.items()})
    try:
        last = mem.recent_runs(5)
        if last and not world.last_goal:
            world.last_goal = last[0]["goal"]
        previous_turn = mem.last_completed_turn_meta(session_id=session_id)
        if previous_turn:
            world.last_outputs["last_turn_meta"] = previous_turn
        previous = mem.last_completed_output(session_id=session_id)
        if previous and previous.get("output") is not None and "last_result" not in world.last_outputs:
            world.last_outputs["last_result"] = previous["output"]
            world.last_outputs["last_result_meta"] = previous
    except Exception:
        pass
    state.world = world

    resolved_goal, needs_context = resolve_goal(goal, world, session_id=session_id)
    if needs_context:
        state.status, state.final_message = "needs_user", "محتاج أعرف المقصود من السياق السابق"
        state.plan = Plan([])
        mem.start_run(state.run_id, state.trace_id, goal, state.plan.to_dict(), session_id=session_id)
        _checkpoint(state, mem, state.status)
        _audit({"event": "context", "resolved": None, "needs_clarification": True}, state.trace_id, state.run_id)
        mem.record_run(goal, state.status, {"steps": []}, state.final_message)
        pop_session(session_token)
        return state

    understanding = understand(resolved_goal)
    semantic = semantic_understand(resolved_goal, mem=mem, world=state.world, registry=registry, session_id=session_id)
    semantic_contract = SemanticContract.from_parse(semantic)
    _audit({
        "event": "conversation_classified",
        "conversation_class": semantic_contract.conversation_class,
        "intent": semantic_contract.intent,
        "operation": semantic_contract.operation,
        "needs_clarification": semantic_contract.needs_clarification,
    }, state.trace_id, state.run_id)
    social_responses = {
        "greeting": "أهلًا بيك 👋 أنا شوري.",
        "how_are_you": "أنا شغال كويس 😄 وإنت عامل إيه؟",
        "thanks": "العفو!",
        "goodbye": "مع السلامة!",
        "acknowledgement": "تمام.",
    }
    social_intent = semantic.top_intent
    social_allowed = semantic_contract.conversation_class == "SOCIAL" and social_intent is not None and social_intent.name in social_responses
    if social_allowed and (social_intent.confidence >= 0.78 or getattr(semantic, "speech_act", None) == "greeting"):
        state.plan = Plan([])
        state.status = "completed"
        state.final_message = social_responses[social_intent.name]
        mem.start_run(state.run_id, state.trace_id, state.goal, state.plan.to_dict(), session_id=session_id)
        _checkpoint(state, mem, state.status)
        _audit({"event": "social_turn", "kind": social_intent.name, "confidence": social_intent.confidence}, state.trace_id, state.run_id)
        mem.record_run(goal, state.status, state.plan.to_dict(), state.final_message)
        mem.update_run(state.run_id, state.status, state.plan.to_dict(), state.final_message)
        try:
            mem.observe(goal, assistant_text=state.final_message, outcome=state.status, session_id=session_id, run_id=state.run_id,
                        entities=[{"type": getattr(e, "type", "entity"), "text": getattr(e, "text", str(e))} for e in getattr(semantic, "entities", ())],
                        experience_kind="interaction",
                        metadata={"social_turn": social_intent.name, "runtime": "legacy"})
        except Exception:
            pass
        try:
            save_session_world(mem, session_id, state.world)
        except Exception:
            pass
        pop_session(session_token)
        return state

    if semantic.needs_clarification:
        state.status = "needs_user"
        state.final_message = semantic.clarification_question or "محتاج توضيح قبل التنفيذ"
        state.plan = Plan([])
        mem.start_run(state.run_id, state.trace_id, goal, state.plan.to_dict(), session_id=session_id)
        _checkpoint(state, mem, state.status)
        _audit({"event": "semantic_clarification", "question": state.final_message,
                "required_information": list(semantic.required_information),
                "ambiguity_reasons": list(semantic.ambiguity_reasons)}, state.trace_id, state.run_id)
        mem.update_run(state.run_id, state.status, state.plan.to_dict(), state.final_message)
        mem.record_run(goal, state.status, {"steps": []}, state.final_message)
        pop_session(session_token)
        return state
    _audit({"event": "understanding", "normalized": understanding.normalized,
            "intents": [i.__dict__ for i in understanding.intents],
            "entities": understanding.entities, "ambiguous": understanding.ambiguous,
            "semantic": semantic.to_dict()}, state.trace_id, state.run_id)

    planning_goal = resolved_goal
    # Compile once at the intelligence boundary. The planner receives structured intent
    # and keeps the user's wording available for argument grounding. This is fully
    # Execution remains deterministic after semantic parsing.
    try:
        task_ir = compile_task_ir(semantic, world=state.world)
    except Exception as exc:
        task_ir = None
        mem.record_event("task_ir_compile_error", {"run_id": state.run_id, "error": str(exc)[:500]})

    # Layer 2 can normalize natural declarative facts (for example "I'm from Luxor")
    # into the canonical goal understood by the existing planner. Restrict this bridge
    # to simple fact/preference writes so compound pipelines keep their original dataflow.
    if (not semantic.needs_clarification
            and semantic.canonical_goal
            and semantic.canonical_goal != resolved_goal
            and semantic.top_intent is not None
            and semantic.top_intent.name == "remember_fact"
            and any(k.startswith("fact:") for k in semantic.slots)
            # Only bridge when the raw surface is not already executable. This preserves
            # user-entered casing and existing legacy matchers for statements such as
            # "my city is Cairo", while enabling novel fact syntax such as "I'm from Luxor".
            and not registry["remember_fact"].matches(resolved_goal)
            and "operation:expression" not in semantic.slots
            and "result:key" not in semantic.slots
            and "research:query" not in semantic.slots):
        planning_goal = semantic.canonical_goal
    # The V23 Brain owns the learned model-based planner on the primary path. The mature
    # legacy runtime still records the same learning data, but does not silently let a
    # globally accumulated learned edge replace its deterministic recovery behavior.
    # Legacy learned-planning can be explicitly enabled for callers that need it.
    learned_legacy_planning = os.getenv("SHURY_ENABLE_LEARNED_LEGACY_PLANNER", "0").strip().lower() in {"1", "true", "yes", "on"}
    planner_learning = learning if learned_legacy_planning else None
    state.plan = _call_planner(planner, planning_goal, mem, state.world, task_ir=task_ir, learning=planner_learning, registry=registry)
    # Constraints can tighten run limits without requiring the planner to trust a user string blindly.
    constraints = getattr(planner, "last_constraints", None) or {}
    if constraints.get("max_steps") is not None:
        state.max_steps = min(state.max_steps, int(constraints["max_steps"]))
    errors = validate(state.plan, registry)
    if errors:
        state.status, state.final_message = "failed", "خطة غير صالحة: " + " ; ".join(errors)
    else:
        decision = decide(understanding, state.plan, registry, semantic=semantic)
        _audit({"event": "decision", "action": decision.action, "confidence": decision.confidence,
                "reason": decision.reason, "risk": decision.risk}, state.trace_id, state.run_id)
        if decision.action == "clarify":
            state.status, state.final_message = "needs_user", decision.reason
        else:
            _prepare_run(state, mem, session_id)
            _execute(state, registry, mem, approve, max_replans=max_replans, context_goal=planning_goal)

    if state.plan is None:
        state.plan = Plan([])
    # Convert machine output into a user-facing answer only after execution/verification
    # has completed. The composer is deterministic; it never invents unsupported facts.
    state.final_message = compose_final_response(
        goal, semantic, state.plan, state.status, fallback=state.final_message
    )
    mem.record_run(goal, state.status, state.plan.to_dict(), state.final_message)
    mem.update_run(state.run_id, state.status, state.plan.to_dict(), state.final_message)
    # Persist a durable episode for long-term memory. Fact/preference promotion is
    # conservative and only happens for explicit statements; ordinary interaction
    # remains episodic until retrieval/consolidation needs it.
    try:
        tool_events = []
        for step in (state.plan.steps if state.plan else []):
            if getattr(step, "status", "") not in {"done", "failed"}:
                continue
            tool_events.append({
                "step_id": getattr(step, "id", ""),
                "tool": getattr(step, "tool", ""),
                "args": getattr(step, "args", {}) or {},
                "output": getattr(step, "output", None),
                "error": getattr(step, "error", "") or None,
                "status": getattr(step, "status", ""),
                "attempts": getattr(step, "attempts", 1),
            })
        mem.observe(goal, assistant_text=state.final_message, outcome=state.status,
                    session_id=session_id, run_id=state.run_id,
                    tool_events=tool_events,
                    entities=[{"type": getattr(e, "type", "entity"), "text": getattr(e, "text", str(e))} for e in getattr(semantic, "entities", ())],
                    experience_kind="task" if tool_events else "interaction",
                    metadata={
                        "planner": state.plan.planner if state.plan else None,
                        "replans": state.replans,
                        "goal_key": normalize(goal),
                        "plan_steps": [s.tool for s in (state.plan.steps if state.plan else []) if s.status == "done"],
                        "runtime": "legacy",
                    })
    except Exception as exc:
        mem.record_event("memory_observation_error", {"run_id": state.run_id, "error": str(exc)})

    try:
        save_session_world(mem, session_id, state.world)
    except Exception as exc:
        mem.record_event("world_session_save_error", {"run_id": state.run_id, "error": str(exc)})

    if state.status == "completed":
        try:
            actual_cost = sum(registry[s.tool].cost for s in state.plan.steps if s.status == "done")
            actual_duration = state.world.elapsed
            mem.cache_plan(normalize(resolved_goal), state.plan.to_dict(), actual_cost, actual_duration)
        except Exception:
            pass
    elif state.status == "failed":
        try:
            mem.record_plan_failure(normalize(resolved_goal))
        except Exception:
            pass
    try:
        learning_result = learning.observe_run(state, mem, registry=registry)
        mem.record_event("self_improvement", {"run_id": state.run_id, "status": state.status, "learning": learning_result})
    except Exception as exc:
        mem.record_event("self_improvement_error", {"run_id": state.run_id, "error": str(exc)[:400]})
    _audit({"event": "end", "status": state.status, "replans": state.replans,
            "planner": state.plan.planner if state.plan else None}, state.trace_id, state.run_id)
    pop_session(session_token)
    return state


def _recover_recorded_effects(state: AgentState, registry: dict, mem) -> int:
    """Recover verified effects that were durably recorded before a checkpoint was written."""
    recovered = 0
    for step in state.plan.steps:
        if step.status != "pending":
            continue
        effect = mem.latest_effect(state.run_id, step.id)
        if not effect or not effect["ok"] or not effect["verified"]:
            continue
        tool = registry.get(step.tool)
        if tool is None:
            continue
        # A verified ledger row is evidence that the side effect completed. Reusing the
        # recorded output avoids duplicating work even for non-idempotent tools.
        step.output = effect["output"]
        step.status = "done"
        step.attempts = effect["attempt"]
        state.outputs[step.id] = effect["output"]
        state.world.transition(StateDelta(add=tool.produces, remove=tool.removes,
                                          resource_delta=tool.resource_costs),
                               effect["duration_ms"] / 1000.0, f"recover:{tool.name}")
        state.world.last_outputs["last_result"] = effect["output"]
        recovered += 1
        mem.record_event("effect_recovery", {"run_id": state.run_id, "step": step.id,
                                              "tool": tool.name, "effect_id": effect["id"]})
        _audit({"event": "effect_recovery", "step": step.id, "tool": tool.name,
                "effect_id": effect["id"]}, state.trace_id, state.run_id)
    return recovered


def resume_agent(run_id: str, approve: Callable[[str, dict], bool] = lambda t, a: True,
                 max_steps: int = 6, max_seconds: float = 30.0, max_replans: int = 2) -> AgentState:
    mem = get_memory()
    cp = mem.load_checkpoint(run_id)
    if not cp:
        raise KeyError(f"run غير موجود: {run_id}")
    state = AgentState(goal=cp["goal"], max_steps=max_steps, max_seconds=max_seconds,
                       status=cp["status"], run_id=run_id)
    if cp["status"] in {"cancelled", "blocked", "failed", "completed", "needs_user"}:
        raise ValueError(f"run غير قابل للاستئناف في الحالة: {cp['status']}")
    state.plan = Plan.from_dict(cp["plan"])
    state.outputs = dict(cp["outputs"])
    state.world = WorldState.from_snapshot(cp["world"])
    state.next_index = int(cp["next_index"])
    rows = mem._q("SELECT trace_id FROM runtime_runs WHERE run_id=?", (run_id,))
    state.trace_id = rows[0][0] if rows else state.trace_id
    registry = load_tools()
    errors = validate(state.plan, registry)
    if errors:
        state.status, state.final_message = "failed", "checkpoint plan غير صالح: " + " ; ".join(errors)
        _checkpoint(state, mem, state.status)
        return state
    # Resume from durable statuses, not from a newly generated plan.
    for node in state.plan.steps:
        if node.status == "skipped":
            node.status = "pending"
    state.status = "running"
    recovered = _recover_recorded_effects(state, registry, mem)
    _audit({"event": "resume", "next_index": state.next_index, "checkpoint_revision": cp.get("revision"),
            "recovered_effects": recovered}, state.trace_id, state.run_id)
    _execute(state, registry, mem, approve, max_replans=max_replans)
    try:
        resumed_semantic = semantic_understand(state.goal, mem=mem, world=state.world, registry=registry)
        state.final_message = compose_final_response(state.goal, resumed_semantic, state.plan, state.status, fallback=state.final_message)
    except Exception:
        pass
    mem.record_run(state.goal, state.status, state.plan.to_dict(), state.final_message)
    _audit({"event": "end", "status": state.status, "resumed": True}, state.trace_id, state.run_id)
    return state


def replay_run(run_id: str) -> list[dict]:
    return get_memory().effects(run_id)


def reliability_report():
    from app.intelligence.reliability import compute
    return compute(get_memory())


def plan_cache():
    return get_memory().plan_cache_stats()


def plan_only(goal: str, planner: Planner | None = None):
    planner = planner or RulePlanner()
    mem = get_memory()
    world = WorldState()
    task_ir = None
    try:
        semantic = semantic_understand(goal, mem=mem, world=world, registry=load_tools())
        task_ir = compile_task_ir(semantic, world=world)
    except Exception:
        # Keep plan_only backward compatible even when semantic compilation cannot be
        # produced; the mature legacy planner remains a valid fallback.
        task_ir = None
    plan = _call_planner(planner, goal, mem, world, task_ir=task_ir)
    return plan, validate(plan, load_tools())

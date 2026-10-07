from __future__ import annotations

from typing import Any
import os

from app.domain.plan import Plan, PlanStep
from app.domain.state import AgentState
from app.brain.models import GoalSpec
from app.brain import CognitiveKernel, BrainResult
from app.knowledge.memory import LAST_RESULT_IGNORED_TOOLS, get_memory
from app.planning.planner import RulePlanner
from app.runtime.registry import load_tools
from app.intelligence.semantic.contract import SemanticContract
from app.world.store import load_session_world


CANONICAL_COGNITIVE_PATH = "shury_core"

def _brain_result_to_agent_state(result: BrainResult, goal: str, *, max_steps: int, max_seconds: float) -> AgentState:
    runtime = result.runtime_state if isinstance(result.runtime_state, dict) else {}
    cognitive = result.state
    done_ids = {
        str(event.get("step"))
        for event in cognitive.trace
        if isinstance(event, dict) and event.get("kind") == "step_completed"
    }
    failed_ids = {
        str(event.get("step"))
        for event in cognitive.trace
        if isinstance(event, dict) and event.get("kind") == "action_observed" and not event.get("ok")
    }
    steps: list[PlanStep] = []
    logical_memory_output = None
    if (getattr(getattr(cognitive, "semantic", None), "requested_operation", "") == "query_identity"
            and getattr(getattr(cognitive, "decision", None), "answer_source", "") in {"memory", "beliefs"}
            and getattr(getattr(cognitive, "decision", None), "evidence", ())):
        first = getattr(cognitive.decision, "evidence", ())[0]
        content = str(getattr(first, "content", "") or "").strip()
        if " = " in content:
            logical_memory_output = content.split(" = ", 1)[1].strip()
        elif content:
            logical_memory_output = content
    for action in list(getattr(cognitive, "plan", ()) or ()):
        sid = str(getattr(action, "step_id", ""))
        status = "done" if sid in done_ids else "failed" if sid in failed_ids else "pending"
        output = (runtime.get("outputs") or {}).get(sid)
        # Identity retrieval is performed by the canonical Brain belief store, not by executing
        # the legacy `recall_fact` tool. Expose that observed result in the compatibility AgentState
        # without pretending that a real-world tool side effect occurred.
        if output is None and logical_memory_output is not None and str(getattr(action, "tool", "")) == "recall_fact":
            status = "done"
            output = logical_memory_output
        steps.append(PlanStep(
            id=sid,
            tool=str(getattr(action, "tool", "") or ""),
            args=dict(getattr(action, "args", {}) or {}),
            status=status,
            output=output,
            capability=str(getattr(action, "capability", "") or ""),
            depends_on=list(getattr(action, "depends_on", ()) or ()),
        ))
    decision_kind = str(getattr(cognitive.decision, "kind", "") or "").strip().casefold()
    result_status = str(result.status or "completed")
    # A Brain clarification is a user-interaction state even when the kernel completed
    # the current deliberation cycle without an execution error.
    if result_status == "completed" and (decision_kind == "clarify" or getattr(cognitive, "planner", "") == "brain-clarify"):
        result_status = "needs_user"
    state = AgentState(
        goal=goal,
        status=result_status,
        max_steps=max_steps,
        max_seconds=max_seconds,
        plan=Plan(
            steps=steps,
            planner=f"brain-{getattr(cognitive.decision, 'kind', 'core')}",
            diagnostics={"semantic_engine": "arabic-retrieval-v1.0", "canonical_brain": True,
                         "company_assignment": dict(runtime.get("company_assignment") or {})},
        ),
        final_message=str(result.response or ""),
        run_id=str(result.run_id or ""),
    )
    state.outputs = dict(runtime.get("outputs") or {})
    state.replans = int(runtime.get("replans") or 0)
    return state


def _semantic_to_structured_payload(contract: SemanticContract) -> dict[str, Any]:
    """Convert the language-neutral SemanticContract into the Brain gateway payload."""
    slots = contract.slots_dict
    target = contract.target
    target_type = "reference" if contract.reference else ""
    if not target and contract.entities:
        first_entity = contract.entities[0]
        target = str(first_entity.get("canonical") or first_entity.get("normalized") or first_entity.get("text") or "")
        target_type = str(first_entity.get("type") or "entity")
    return {
        "goal": str(contract.canonical_goal or contract.text).strip(),
        "operation": str(contract.executable_operation).strip(),
        "capability": str(contract.capability).strip(),
        "target": target,
        "target_type": target_type,
        "slots": slots,
        "constraints": [
            f"{item['key']} {item['operator']} {item['value']}"
            for item in contract.constraints
        ],
        "temporal_requirements": [
            f"{item['kind']}:{' -> '.join(x for x in (item.get('start', ''), item.get('end', '')) if x) or item.get('text', '')}"
            for item in contract.temporal
        ],
        "required_evidence": list(contract.required_information),
        "priority": 0.5,
        "language": contract.language,
    }


def _persist_brain_world_result(result: BrainResult, memory: Any, session_id: str | None) -> None:
    """Mirror the canonical Brain's latest observed result into the durable session world.

    This is runtime/session state, not learning state. It keeps the existing world-state
    continuity contract available across turns/devices while the Brain's cognitive evidence
    remains canonical in BrainStateStore/LearningStore.
    """
    if memory is None or not session_id:
        return
    try:
        from app.world.store import load_session_world, save_session_world
        world = load_session_world(memory, session_id)
        runtime = result.runtime_state if isinstance(result.runtime_state, dict) else {}
        outputs = runtime.get("outputs") or {}
        if outputs:
            last_id = next(reversed(outputs))
            last_action = next((
                action for action in (getattr(result.state, "plan", ()) or ())
                if str(getattr(action, "step_id", "")) == str(last_id)
            ), None)
            if str(getattr(last_action, "tool", "")) not in LAST_RESULT_IGNORED_TOOLS:
                world.last_outputs["last_result"] = outputs[last_id]
                world.last_outputs["last_result_step"] = str(last_id)
                world.last_outputs["last_result_run_id"] = str(result.run_id or "")
        if result.response:
            world.last_outputs["last_response"] = str(result.response)[:4000]
        if getattr(result.state, "goal", None) is not None:
            world.last_goal = str(result.state.goal.objective or "")[:4000]

        # Keep the durable session WorldState observation trail aligned with the
        # canonical Brain execution evidence. This is continuity state only; it
        # does not become a learning or decision authority store.
        state_observations = getattr(result.state, "observations", None) or []
        if isinstance(state_observations, list):
            existing_keys = {
                (str(item.get("step_id", "")), str(item.get("timestamp", "")))
                for item in world.observations
                if isinstance(item, dict)
            }
            for item in state_observations[-20:]:
                if not isinstance(item, dict):
                    continue
                observation = dict(item)
                key = (str(observation.get("step_id", "")), str(observation.get("timestamp", "")))
                if key in existing_keys:
                    continue
                world.observations.append(observation)
                existing_keys.add(key)
            world.observations = world.observations[-50:]

        save_session_world(memory, session_id, world)
    except Exception:
        # Compatibility persistence must never gain execution authority or break a completed run.
        return


def run_cognitive(
    goal: str,
    approve=lambda t, a: True,
    max_steps: int = 10,
    max_seconds: float = 180.0,
    max_bad_replies: int = 3,
    max_reflections: int = 10,
    session_id: str | None = None,
    kernel: CognitiveKernel | None = None,
) -> AgentState:
    """Canonical natural-language entrypoint using Arabic-Retrieval NLP + Brain execution.

    Language understanding is retrieval-based. Planning, policy, execution, verification,
    learning, and response generation remain inside the deterministic Brain stack.
    """
    brain = kernel or CognitiveKernel()
    from app.intelligence.semantic import SemanticInterpreter, LanguagePatternCache
    from app.learning.store import LearningStore, DEFAULT_PATH

    mem = brain.memory if getattr(brain, "memory", None) is not None else get_memory()
    pattern_store = LearningStore(os.environ.get("AGENT_LEARNING_DB") or DEFAULT_PATH)
    pattern_cache = LanguagePatternCache(pattern_store)
    registry = load_tools()
    world = load_session_world(mem, session_id)
    try:
        previous = mem.last_completed_output(session_id=session_id)
        if previous and previous.get("output") is not None:
            world.last_outputs["last_result"] = previous["output"]
            world.last_outputs["last_result_meta"] = previous
    except Exception:
        pass

    semantic = SemanticInterpreter(pattern_cache=pattern_cache).parse(
        goal, mem=mem, world=world, registry=registry, session_id=session_id
    )
    semantic_contract = SemanticContract.from_parse(semantic)
    if semantic_contract.needs_clarification:
        state = AgentState(goal=goal, status="needs_user", max_steps=max_steps, max_seconds=max_seconds)
        state.plan = Plan([], planner="retrieval-nlp-clarify", diagnostics={
            "semantic_engine": "arabic-retrieval-v1.0",
            "canonical_brain": True,
            "semantic_parse": semantic_contract.to_dict(),
        })
        state.final_message = semantic.clarification_question or "محتاج توضيح قبل التنفيذ."
        return state

    payload = _semantic_to_structured_payload(semantic_contract)
    result = brain.act_structured(payload, approve=approve, session_id=session_id, max_steps=max_steps)
    _persist_brain_world_result(result, mem, session_id)
    state = _brain_result_to_agent_state(result, goal, max_steps=max_steps, max_seconds=max_seconds)
    if state.status == "needs_user" and semantic.clarification_question:
        state.final_message = semantic.clarification_question
    state.plan.diagnostics.update({
        "semantic_engine": "arabic-retrieval-v1.0",
        "semantic_source": semantic_contract.source,
        "semantic_confidence": semantic_contract.confidence,
    })
    return state


def run_structured_cognitive(
    payload: dict,
    *,
    approve=lambda t, a: True,
    max_steps: int = 10,
    session_id: str | None = None,
    kernel: CognitiveKernel | None = None,
):
    """Execute a canonical structured GoalSpec without invoking a language model."""
    result = (kernel or CognitiveKernel()).act_structured(payload, approve=approve, session_id=session_id, max_steps=max_steps)
    return result

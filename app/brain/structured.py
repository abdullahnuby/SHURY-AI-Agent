"""Structured-goal adapter.

This module turns an already validated structured goal into the Brain's canonical
GoalSpec + deterministic SemanticFrame. It contains no model/provider dependency.
"""
from __future__ import annotations

from typing import Any, Mapping

from app.brain.models import GoalSpec, SemanticFrame


_OFFLINE_OPERATIONS = {
    "calculate": ("calculation",),
    "calculator": ("calculation",),
    "perform_calculation": ("calculation",),
    "remember": ("memory",),
    "forget_memory": ("memory",),
    "maintain_memory": ("memory",),
    "remember_fact": ("memory",),
    "query_time": ("time",),
    "query_identity": ("person_identity",),
    "query_memory": ("memory",),
    "query_capabilities": ("capability",),
    "research": ("research",),
    "learning_intent": ("learning",),
    "self_improvement_research": ("learning", "research"),
    "project_task": ("project",),
    "development_validation": ("project", "validation"),
    "development_inspection": ("project", "inspection"),
    "data_analysis": ("data", "analysis"),
    "skill_query": ("skill",),
}


def _clean_text(value: Any, *, field: str, max_len: int = 4000) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_len:
        raise ValueError(f"{field} is too long")
    return text


def _string_tuple(value: Any, *, field: str, max_items: int = 32, max_len: int = 500) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be an array of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} has too many items")
    result: list[str] = []
    for item in value:
        text = _clean_text(item, field=field, max_len=max_len)
        result.append(text)
    return tuple(result)


def _mapping_strings(value: Any, *, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    if len(value) > 32:
        raise ValueError(f"{field} has too many keys")
    result: dict[str, str] = {}
    for key, item in value.items():
        key_text = _clean_text(key, field=f"{field}.key", max_len=120)
        value_text = _clean_text(item, field=f"{field}.{key_text}", max_len=1200)
        result[key_text] = value_text
    return result


def _normalize_operation(name: str, capability: str | None) -> str:
    candidate = str(name or capability or "").strip().casefold()
    aliases = {
        "compute": "calculate",
        "calc": "calculate",
        "save": "remember",
        "remember_fact": "remember",
        "forget_fact": "forget_memory",
        "remember_result": "compound_calculate_remember",
        "recall_fact": "query_identity",
        "recall_last_result": "query_identity",
        "time": "query_time",
        "search": "research",
        "scientific_research": "research",
        "research_memory_search": "research",
        "memory_search": "query_memory",
        "memory_profile": "query_memory",
        "memory_stats": "query_memory",
        "history": "query_memory",
        "file_read": "file_read",
        "learn": "learning_intent",
        "inspect": "development_inspection",
        "validate": "development_validation",
        "profile_dataset": "data_analysis",
        "analyze_dataset": "data_analysis",
    }
    return aliases.get(candidate, candidate)


def validate_structured_goal(payload: Mapping[str, Any]) -> tuple[GoalSpec, SemanticFrame, dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise ValueError("structured goal must be an object")

    objective = _clean_text(payload.get("goal") or payload.get("objective"), field="goal")
    name = _normalize_operation(payload.get("operation") or payload.get("name") or payload.get("goal") or "", payload.get("capability"))
    capability = str(payload.get("capability") or "").strip()
    target = str(payload.get("target") or "").strip()
    parameters = _mapping_strings(payload.get("parameters"), field="parameters")
    slots = _mapping_strings(payload.get("slots"), field="slots")
    slots.update(parameters)
    # Layer-2 semantic names are namespaced to keep their origin explicit. The Brain
    # canonical frame uses stable action slots, so normalize the gateway vocabulary here.
    slot_aliases = {
        "operation:expression": "expression",
        "result:key": "result_key",
        "recall:key": "key",
        "fact:generic": "predicate",
    }
    raw_slots = dict(slots)
    for source, canonical in slot_aliases.items():
        if source not in raw_slots or canonical in slots:
            continue
        slots[canonical] = raw_slots[source]
    if "fact:name" in raw_slots:
        slots.setdefault("predicate", "name")
    if "fact:city" in raw_slots:
        slots.setdefault("predicate", "city")
    if "fact:origin" in raw_slots:
        slots.setdefault("predicate", "origin")
    if "fact:job" in raw_slots:
        slots.setdefault("predicate", "job")
    if "fact:preference" in raw_slots:
        slots.setdefault("predicate", "preference")
    if "preference:general" in raw_slots:
        slots.setdefault("predicate", "preference")
        slots.setdefault("value", raw_slots["preference:general"])
    if "preference:theme" in raw_slots:
        slots.setdefault("predicate", "theme")
        slots.setdefault("value", raw_slots["preference:theme"])
    # `recall_fact` is a generic semantic operation. Only the name key is an identity query;
    # all other keys belong to generic memory so city/origin/language cannot be routed to name.
    # The semantic fact parser yields the value under the fact namespace; the stable Brain
    # contract always calls it `value`.
    for source in ("fact:name", "fact:city", "fact:origin", "fact:job", "fact:preference", "preference:general", "preference:theme"):
        if source in raw_slots:
            slots.setdefault("value", raw_slots[source])
    if name == "query_identity" and slots.get("key") and slots.get("key") != "name":
        name = "query_memory"
    elif name == "query_memory" and slots.get("key") == "name":
        name = "query_identity"

    if target:
        # These mappings deliberately fill only canonical slots. The Brain planner
        # remains responsible for matching the tool contract and validating args.
        if name in {"calculate", "calculator", "perform_calculation"} and "expression" not in slots:
            slots["expression"] = target
        elif name in {"research", "learning_intent", "self_improvement_research", "query_knowledge"} and "query" not in slots:
            slots["query"] = target
        elif "target" not in slots:
            slots["target"] = target

    if not name and capability:
        name = _normalize_operation(capability, capability)
    if not name:
        raise ValueError("operation or capability is required")

    concepts = set(_OFFLINE_OPERATIONS.get(name, ()))
    concepts.add(name)
    if capability:
        concepts.add(capability)

    language = str(payload.get("language") or "en").strip().casefold()
    if language not in {"en", "ar", "mixed", "other"}:
        raise ValueError("language must be en, ar, mixed or other")
    actionability = "information" if name in {"query_time", "query_identity", "query_memory", "query_capabilities", "research", "learning_intent", "self_improvement_research", "query_knowledge"} else "action"

    required_information = list(_string_tuple(payload.get("required_information"), field="required_information"))
    if name in {"calculate", "calculator", "perform_calculation"} and not slots.get("expression"):
        required_information.append("expression")
    if name in {"remember", "maintain_memory", "remember_fact"}:
        if not slots.get("key") and not slots.get("predicate"):
            required_information.append("key")
        if "value" not in slots:
            required_information.append("value")
    required_information = list(dict.fromkeys(required_information))

    constraints = _string_tuple(payload.get("constraints"), field="constraints")
    success_conditions = _string_tuple(
        payload.get("success_conditions") or payload.get("desired_state"),
        field="success_conditions",
    )
    desired_state = success_conditions
    required_evidence = _string_tuple(payload.get("required_evidence"), field="required_evidence")
    priority = payload.get("priority", 0.5)
    try:
        priority = max(0.0, min(1.0, float(priority)))
    except (TypeError, ValueError) as exc:
        raise ValueError("priority must be numeric") from exc

    # Data analysis can safely address the active dataset when the structured caller
    # intentionally omits a literal path; the data tool itself resolves/validates the
    # workspace reference before execution.
    if name == "data_analysis" and not slots.get("path"):
        slots["path"] = target or "@active_dataset"
    query = str(payload.get("query") or slots.get("query") or (target if name in {"research", "learning_intent", "self_improvement_research", "query_knowledge"} else "")).strip()
    frame = SemanticFrame(
        text=objective,
        language=language,
        speech_act="command",
        concepts=tuple(sorted(concepts)),
        entities=((target, str(payload.get("target_type") or "target")),) if target else (),
        requested_operation=name,
        object_text=target,
        slots=tuple(sorted(slots.items())),
        question_type="" if actionability == "action" else "structured",
        temporal=_string_tuple(payload.get("temporal_requirements") or payload.get("temporal"), field="temporal_requirements"),
        conditions=(),
        uncertainty=tuple(sorted(set(required_information))),
    )
    goal = GoalSpec(
        name=name,
        objective=objective,
        desired_state=desired_state,
        constraints=constraints,
        success_conditions=success_conditions,
        query=query,
        required_evidence=required_evidence,
        priority=priority,
    )
    metadata = {
        "source": "structured_goal",
        "target": target,
        "capability": capability,
        "parameters": parameters,
        "slots": slots,
        "priority": priority,
    }
    return goal, frame, metadata


__all__ = ["validate_structured_goal"]

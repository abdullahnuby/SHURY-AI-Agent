from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import SemanticParse

CONTRACT_VERSION = "1.0"


@dataclass(frozen=True)
class SemanticContract:
    """Single typed semantic hand-off shared by interface and Brain layers.

    `slots` remains the extensible carrier, while the fields below are the canonical
    decision fields. Producers are retrieval-native semantic parsing; Brain is the
    primary consumer. No generative model is involved.
    """

    version: str = CONTRACT_VERSION
    text: str = ""
    normalized: str = ""
    language: str = "other"
    language_variant: str = "unknown"
    domain: str = "general"
    conversation_class: str = "TASK"
    speech_act: str = "request"
    actionability: str = "action"
    intent: str = ""
    capability: str = ""
    operation: str = ""
    canonical_goal: str = ""
    target: str = ""
    key: str = ""
    value: str = ""
    expression: str = ""
    reference: str = ""
    entities: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    references: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    temporal: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    constraints: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    slots: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    uncertainty: tuple[str, ...] = field(default_factory=tuple)
    required_information: tuple[str, ...] = field(default_factory=tuple)
    ambiguity_reasons: tuple[str, ...] = field(default_factory=tuple)
    safety_signals: tuple[str, ...] = field(default_factory=tuple)
    needs_clarification: bool = False
    clarification_question: str = ""
    confidence: float = 0.0
    requires_fresh_data: bool = False
    source: str = "retrieval-nlp"
    memory_need: str = "none"
    memory_types: tuple[str, ...] = field(default_factory=tuple)
    memory_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("entities", "references", "temporal", "constraints"):
            data[key] = list(data[key])
        data["slots"] = dict(data["slots"])
        return data

    @property
    def slots_dict(self) -> dict[str, str]:
        return dict(self.slots)

    @property
    def executable_operation(self) -> str:
        return self.operation or self.intent


def _first_slot(parse: SemanticParse, *names: str) -> str:
    slots = parse.slots
    for name in names:
        value = slots.get(name)
        if value:
            return str(value)
    return ""


def _fact_value(parse: SemanticParse) -> str:
    for key, value in parse.slots.items():
        if key.startswith("fact:") and value:
            return str(value)
    return ""


def _fact_key(parse: SemanticParse) -> str:
    for key in parse.slots:
        if key.startswith("fact:"):
            return key.split(":", 1)[1]
    return ""


def _conversation_class(parse: SemanticParse) -> str:
    """Classify the turn before execution routing.

    The ordering is intentional: uncertainty/correction and conversational state must
    dominate executable surface signals, while factual system/knowledge questions stay
    informational instead of being promoted to generic tasks.
    """
    intent = (parse.top_intent.name if parse.top_intent else "").casefold()
    social = {"greeting", "how_are_you", "thanks", "goodbye", "acknowledgement"}
    memory_write = {"remember_fact", "remember_memory", "remember_result", "remember_last_result", "forget_fact"}
    memory_read = {"recall_fact", "memory_search", "memory_profile", "memory_stats", "history"}
    research = {"web_research", "scientific_research", "open_world_learning", "rag_reasoning", "agentic_rag"}
    analysis = {"data_analysis", "workspace_reasoning", "workspace_inventory", "workspace_recursive_inventory", "workspace_file_organization", "workspace_duplicate_cleanup"}
    information = {"query_knowledge", "knowledge_query", "query_capabilities", "capabilities", "query_time", "time"}
    execution = {"calculate", "project_audit", "development_validation", "development_inspection", "development_git", "skill_acquisition", "skill_lifecycle", "project_task", "skill_query", "skill_discovery"}

    if intent in social:
        return "SOCIAL"
    # A correction or unresolved reference is a conversational control state, not an
    # executable task. It must stop before planning regardless of the noisy top intent.
    if parse.speech_act == "correction" or parse.needs_clarification:
        return "CLARIFICATION"
    if intent in memory_write:
        return "MEMORY_WRITE"
    if intent in memory_read:
        return "MEMORY_READ"
    if intent in research:
        return "RESEARCH"
    if intent in analysis:
        return "ANALYSIS"
    # Information is defined by the speech act as well as the intent. This prevents a
    # fuzzy task intent from turning a plain knowledge question into an execution task.
    if parse.actionability == "information" or intent in information:
        return "INFORMATION"
    if intent in execution or parse.actionability == "action":
        return "EXECUTION"
    if intent or parse.canonical_goal:
        return "TASK"
    return "INFORMATION"


def from_parse(parse: SemanticParse) -> SemanticContract:
    """Translate exactly one `SemanticParse` into the canonical semantic contract."""
    top = parse.top_intent
    intent = top.name if top else ""
    operation = intent or ""
    expression = _first_slot(parse, "operation:expression", "expression")
    key = _first_slot(parse, "recall:key", "result:key", "key", "correction:key") or _fact_key(parse)
    value = _first_slot(parse, "correction:value", "value") or _fact_value(parse)
    reference = _first_slot(parse, "reference", "reference_target", "reference_target_text")
    target = _first_slot(parse, "target", "reference_target", "query", "question") or parse.canonical_goal
    if not target:
        target = parse.original

    return SemanticContract(
        text=parse.original,
        normalized=parse.normalized,
        language=parse.language,
        language_variant=getattr(parse, "language_variant", "unknown"),
        domain=parse.domain,
        conversation_class=_conversation_class(parse),
        speech_act=parse.speech_act,
        actionability=parse.actionability,
        intent=intent,
        capability=str(top.capability if top else ""),
        operation=operation,
        canonical_goal=parse.canonical_goal,
        target=target,
        key=key,
        value=value,
        expression=expression,
        reference=reference,
        entities=tuple(entity.to_dict() for entity in parse.entities),
        references=tuple(reference.to_dict() for reference in parse.references),
        temporal=tuple(item.to_dict() for item in parse.temporal),
        constraints=tuple(item.to_dict() for item in parse.constraints),
        slots=tuple(sorted((str(k), str(v)) for k, v in parse.slots.items())),
        uncertainty=tuple(parse.ambiguity_reasons) + tuple(parse.required_information),
        required_information=tuple(parse.required_information),
        ambiguity_reasons=tuple(parse.ambiguity_reasons),
        safety_signals=tuple(parse.safety_signals),
        needs_clarification=bool(parse.needs_clarification),
        clarification_question=parse.clarification_question,
        confidence=float(parse.confidence),
        requires_fresh_data=bool(parse.requires_fresh_data),
        source=parse.source,
        memory_need=parse.memory_need,
        memory_types=tuple(parse.memory_types),
        memory_reason=parse.memory_reason,
    )


SemanticContract.from_parse = staticmethod(from_parse)  # type: ignore[attr-defined]


__all__ = ["CONTRACT_VERSION", "SemanticContract", "from_parse"]

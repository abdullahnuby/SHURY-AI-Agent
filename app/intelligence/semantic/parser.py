from __future__ import annotations
from datetime import datetime
import re
from typing import Any, Mapping

from app.intelligence.understanding import normalize, understand
from app.intelligence.answer_policy import infer_knowledge_question_candidate
from app.knowledge.memory import get_memory
from app.runtime.registry import Tool
from .models import SemanticParse, EntityMention, IntentCandidate, Reference, TemporalExpression, SemanticConstraint
from .intents import candidates
from .entities import extract_entities
from .references import resolve_references, _reference_is_task_deictic
from .temporal import extract_temporal
from .constraints import extract_constraints
from .slots import extract_slots
from .brain_prior import apply_brain_priors

KNOWN_DOMAINS = {
    "calculator": "computation", "memory": "memory", "research": "research", "development": "development",
    "analysis": "analysis", "skills": "skills", "knowledge": "research", "system": "system",
}

INTENT_ALIASES = {
    "skill_selection": "skill_query",
}


def _canonicalize_intent_candidates(items: list[IntentCandidate]) -> list[IntentCandidate]:
    out: dict[str, IntentCandidate] = {}
    for item in items:
        name = INTENT_ALIASES.get(item.name, item.name)
        candidate = IntentCandidate(name, item.confidence, item.evidence, item.capability,
                                    item.required_slots, item.missing_slots, item.source)
        previous = out.get(name)
        if previous is None or candidate.confidence > previous.confidence:
            out[name] = candidate
    return sorted(out.values(), key=lambda x: (-x.confidence, x.name))[:10]


def _language(text: str) -> str:
    # Language identification should not be polluted by opaque identifiers such as
    # variable names or saved-result keys embedded inside an otherwise Arabic utterance.
    # We mask identifier slots after bilingual "as/named" markers before counting scripts.
    masked = re.sub(
        r"(?:\bas\b|\bnamed\b|\bunder\s+(?:the\s+)?name\b|باسم|تحت\s+اسم)\s+[A-Za-z0-9_./:-]+",
        " ",
        text,
        flags=re.I,
    )
    ar = len(re.findall(r"[\u0600-\u06ff]", masked))
    en = len(re.findall(r"[A-Za-z]", masked))
    if ar and en and ar >= 2 and en >= 2:
        return "mixed"
    if ar:
        return "ar"
    if en:
        return "en"
    return "other"


def _tool_intents(registry: dict[str, Tool]) -> set[str]:
    names = {i.name for i in understand("calculate 1+1").intents}
    # Keep existing intent names plus the audited semantic route names. Tool names are
    # not intents; this boundary prevents similarity routing from inventing capabilities.
    names.update({
        "calculate", "time", "save_note", "list_notes", "search_notes", "remember_fact", "recall_fact",
        "recall_last_result", "remember_result", "remember_last_result", "memory_search", "memory_profile", "memory_stats", "remember_memory", "forget_fact", "history",
        "web_research", "scientific_research", "research_memory_search", "open_world_learning", "github_discovery", "github_learning",
        "data_analysis", "workspace_reasoning", "development_validation", "development_inspection", "development_learning",
        "development_git", "skill_discovery", "skill_routing", "skill_acquisition", "skill_trust", "skill_lifecycle",
        "rag_reasoning", "agentic_rag", "rag_indexing", "agent_observability",
    })
    return names


def _explicit_social_turn(text: str) -> str | None:
    n = normalize(text)
    patterns = {
        "greeting": r"(?:hello|hi|hey|good\s+(?:morning|afternoon|evening|day)|ahlan|اهلا|أهلا|السلام\s+عليكم|مرحبا|مرحباً|مرحبًا)(?:\s+(?:there|everyone|again|abdullah|بيك|وسهلا|سهلا))?",
        "how_are_you": r"how\s+are\s+you(?:\s+doing)?|how(?:\s+is|['’]s)\s+it\s+going|what['’]s\s+up|how\s+are\s+things|عامل\s+ايه(?:\s+اخبارك)?|إزيك|ازيك|إيه\s+الاخبار|ايه\s+الاخبار",
        "thanks": r"thanks?(?:\s+(?:a\s+lot|so\s+much))?|thank\s+you(?:\s+so\s+much)?|much\s+appreciated|شكرا|شكرًا|متشكر(?:ة)?|تسلم",
        "goodbye": r"goodbye|bye|see\s+you(?:\s+later)?|take\s+care|مع\s+السلامة|سلام",
        "acknowledgement": r"ok(?:ay)?|got\s+it|understood|sure|تمام|ماشي|حاضر",
    }
    for name, pattern in patterns.items():
        if re.fullmatch(rf"(?:{pattern})[!?.؟،,\s]*", n, re.I):
            return name
    return None


def _confidence_gap(items: list[IntentCandidate]) -> float:
    if not items:
        return 0.0
    if len(items) == 1:
        return items[0].confidence
    return max(0.0, items[0].confidence - items[1].confidence)


def _ground_correction_target(goal: str, slots: dict[str, str], mem, session_id: str | None) -> dict[str, str]:
    """Resolve corrections only from explicit semantic memory in the same session."""
    if "correction:value" not in slots or mem is None or not session_id:
        return {}
    try:
        episodes = mem.recent_episodes(session_id=session_id, limit=8)
    except Exception:
        return {}
    for ep in episodes:
        user_text = str(ep.get("user_text") or "").strip()
        if not user_text or normalize(user_text) == normalize(goal):
            continue
        try:
            prior_slots = extract_slots(user_text)
        except Exception:
            continue
        for key, value in prior_slots.items():
            if key.startswith("fact:"):
                return {"correction:key": key.split(":", 1)[1], "correction:previous_value": value}
            if key.startswith("preference:") and key != "preference:general":
                return {"correction:key": key, "correction:previous_value": value}
            if key == "recall:key" and value:
                return {"correction:key": value, "correction:previous_value": ""}
    return {}


def _canonical_goal(original: str, slots: dict[str, str], speech_act: str) -> str:
    """Produce a compact semantic goal without adding facts not present in the input."""
    if slots.get("operation:expression"):
        return f"calculate {slots['operation:expression']}"
    if slots.get("research:query"):
        return f"research {slots['research:query']}"
    if slots.get("result:key"):
        if re.search(r"(?:previous|last)\s+(?:result|output)|النتيجة\s+(?:السابقة|السابق)|الناتج\s+السابق", original, re.I):
            return f"save previous result as {slots['result:key']}"
        return f"save result as {slots['result:key']}"
    if slots.get("recall:key"):
        return f"retrieve my {slots['recall:key']}"
    for key, value in slots.items():
        if key.startswith("fact:"):
            return f"remember {key.split(':',1)[1]} = {value}"
        if key.startswith("preference:") and key != "preference:general":
            return f"remember preference {key.split(':',1)[1]} = {value}"
    if slots.get("correction:key") and slots.get("correction:value"):
        return f"correct {slots['correction:key']} to {slots['correction:value']}"
    return original


def _learning_topic(text: str) -> str:
    """Extract the substantive topic from a learning/research request."""
    n = normalize(text).strip(" ?؟:،,")
    patterns = (
        r"^learn\s+(?:from\s+(?:the\s+)?(?:web|internet)|online)\s+(.+)$",
        r"^learn\s+(.+)$",
        r"^research\s+and\s+learn\s+(?:about\s+)?(.+)$",
        r"^ابحث\s+وتعلم\s+(?:عن\s+)?(.+)$",
        r"^تعلم(?:\s+من\s+(?:الويب|الانترنت|الإنترنت)|\s+اونلاين)?\s+(?:ازاي\s+|كيف\s+)?(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, n, re.I)
        if match:
            topic = re.sub(r"\s+", " ", match.group(1)).strip(" ?؟:،,")
            if topic:
                return topic
    return ""


def _memory_question_signal(text: str) -> bool:
    """Recognize natural questions about remembered context, not time/date."""
    n = normalize(text).strip()
    question = bool(
        re.search(r"^(?:متى|فين|أين|مين|من|هل|what|when|where|who|which|did|do)\b", n, re.I)
        or n.endswith(("?", "؟"))
    )
    memory_markers = (
        "اجتماع", "اجتماعات", "موعد", "ميعاد", "مقابلة", "حجز", "رحلة", "ملاحظة", "ملاحظات",
        "تذكير", "تذكيرات", "اتفاق", "مكالمة", "تسليم", "زيارة", "موعدي",
        "meeting", "appointment", "interview", "booking", "trip", "reminder", "note", "notes",
        "call", "delivery", "visit",
    )
    return question and any(marker in n for marker in memory_markers)


class SemanticInterpreter:
    def __init__(self, pattern_cache=None):
        self.pattern_cache = pattern_cache

    def parse(self, goal: str, mem=None, world=None, registry: dict[str, Tool] | None = None,
              session_id: str | None = None, now: datetime | None = None) -> SemanticParse:
        original = str(goal or "").strip()
        n = normalize(original)
        registry = registry or {}
        if isinstance(world, Mapping):
            last_goal = world.get("last_goal", "")
            last_outputs = world.get("last_outputs", {})
            last_result = (last_outputs or {}).get("last_result") if isinstance(last_outputs, Mapping) else None
        else:
            last_goal = getattr(world, "last_goal", "") if world is not None else ""
            last_outputs = getattr(world, "last_outputs", {}) if world is not None else {}
            last_result = ((last_outputs or {}).get("last_result") if isinstance(last_outputs, Mapping) else None)
        world_data = {
            "last_goal": last_goal,
            "last_outputs": last_outputs,
            "last_result": last_result,
        }
        memory_data = {}
        if mem is None:
            try: mem = get_memory()
            except Exception: mem = None
        if mem is not None:
            try:
                memory_data = mem.recall_context(original, limit=4, session_id=session_id)
            except Exception:
                memory_data = {}
        base_intents = candidates(original)
        slots = extract_slots(original)
        learning_topic = _learning_topic(original)
        if learning_topic:
            slots.setdefault("learning_topic", learning_topic)
            slots.setdefault("research:query", learning_topic)
        # A recall key is authoritative question evidence. Prevent declarative
        # patterns such as "أنا من ..." from stealing a question like
        # "أنا من فين؟" and turning it into a memory write.
        if "recall:key" in slots:
            for key in tuple(slots):
                if key.startswith("fact:"):
                    slots.pop(key, None)
        if _memory_question_signal(original):
            query = re.sub(
                r"^(?:متى|فين|أين|مين|من|هل|ايه|إيه|ما|ماذا|what|when|where|who|which|did|do)\s*",
                "", n, flags=re.I,
            ).strip(" ?؟:،,")
            if query.startswith("ال") and len(query) > 4:
                query = query[2:]
            slots["memory:query"] = query or original
            memory_candidate = IntentCandidate(
                "memory_search", 0.96, ("natural-memory-question",), "memory_search", source="semantic-rule"
            )
            base_intents = [memory_candidate] + [x for x in base_intents if x.name not in {"time", "web_research"}]
        slots.update(_ground_correction_target(original, slots, mem, session_id))
        # High-value identity/memory questions get an explicit deterministic semantic
        # rule so natural forms such as "أنا مين" and "show me what you remember about
        # my name" cannot drift toward a memory-write intent.
        if re.search(r"(?:^|\s)(?:انا|أنا)\s+مين\s*[؟?]?$", n, re.I) or re.search(
            r"\bwhat\s+(?:do\s+you\s+remember|you\s+remember)\s+about\s+my\s+name\b", n, re.I
        ):
            slots["recall:key"] = "name"
            recall_candidate = IntentCandidate("recall_fact", 0.97, ("explicit-identity-recall",), "recall_fact", source="semantic-rule")
            base_intents = [recall_candidate] + [x for x in base_intents if x.name != "recall_fact"]
        entities = extract_entities(original, slots)
        temporal = extract_temporal(original, now=now)
        recent_episodes = []
        if mem is not None and session_id:
            try:
                recent_episodes = mem.recent_episodes(session_id=session_id, limit=8)
            except Exception:
                recent_episodes = []
        protected_reference_tokens = {
            str(entity.text).strip()
            for entity in entities
            if str(getattr(entity, 'type', '')).strip() in {'person', 'organization', 'repository', 'file', 'url', 'email'}
            and str(entity.text).strip()
        }
        references = resolve_references(
            original, world_data, recent_episodes=recent_episodes,
            protected_tokens=protected_reference_tokens,
        )
        # Promote grounded discourse references into the canonical semantic slot contract.
        # Downstream Brain code consumes these stable slots rather than reverse-engineering
        # the Reference objects independently.
        resolved_reference = next((ref for ref in references if ref.resolved and ref.target), None)
        if resolved_reference is not None:
            slots.setdefault("reference_target", str(resolved_reference.target))
        constraints = extract_constraints(original)
        # Semantic slot/reference evidence can disambiguate otherwise similar legacy intents.
        if "recall:key" in slots:
            adjusted = []
            for item in base_intents:
                if item.name == "recall_fact":
                    confidence = 0.98
                    evidence = item.evidence + ("recall-slot-context", "recall-question-priority")
                    source = "semantic-router"
                elif item.name in {"remember_fact", "remember_memory"}:
                    confidence = min(0.18, item.confidence * 0.20)
                    evidence = item.evidence + ("recall-question-priority",)
                    source = "semantic-router"
                else:
                    confidence = item.confidence
                    evidence = item.evidence
                    source = item.source
                adjusted.append(IntentCandidate(item.name, max(0.0, min(0.99, confidence)),
                                               evidence, item.capability,
                                               item.required_slots, item.missing_slots, source))
            if not any(item.name == "recall_fact" for item in adjusted):
                adjusted.append(IntentCandidate(
                    "recall_fact", 0.98, ("recall-slot-context", "recall-question-priority"),
                    "memory", source="semantic-router"
                ))
            base_intents = sorted(adjusted, key=lambda x: (-x.confidence, x.name))[:10]
        if "result:key" in slots:
            preferred = "remember_last_result" if re.search(
                r"(?:previous|last)\s+(?:result|output)|النتيجة\s+(?:السابقة|السابق)|الناتج\s+السابق", n, re.I
            ) else "remember_result"
            boosted = []
            for item in base_intents:
                if item.name == preferred:
                    boosted.append(IntentCandidate(item.name, min(0.99, item.confidence + 0.55),
                                                   item.evidence + ("semantic-context-boost",), item.capability,
                                                   item.required_slots, item.missing_slots, "semantic-router"))
                elif item.name == "save_note":
                    boosted.append(IntentCandidate(item.name, max(0.0, item.confidence - 0.35),
                                                   item.evidence + ("semantic-context-demotion",), item.capability,
                                                   item.required_slots, item.missing_slots, item.source))
                else:
                    boosted.append(item)
            base_intents = sorted(boosted, key=lambda x: (-x.confidence, x.name))[:10]
        if re.search(r"^(?:i\s+prefer|i\s+like|i\s+love|i\s+usually\s+use|انا\s+بفضل|انا\s+احب|انا\s+عادة\s+بستخدم)\b", n, re.I):
            adjusted = []
            for item in base_intents:
                delta = 0.34 if item.name == "remember_memory" else (-0.28 if item.name in {"recall_fact", "memory_profile"} else 0.0)
                adjusted.append(IntentCandidate(item.name, max(0.0, min(0.99, item.confidence + delta)), item.evidence + (("preference-context",) if delta else ()), item.capability, item.required_slots, item.missing_slots, item.source))
            base_intents = sorted(adjusted, key=lambda x: (-x.confidence, x.name))[:10]
        # Declarative fact statements are memory writes, not recall questions.
        # Explicit key/value memory syntax is a hard semantic signal: it must win over
        # fuzzy similarity to unrelated domains such as development/project inspection.
        explicit_fact = any(k.startswith("fact:") for k in slots) and not re.search(
            r"^(?:what|what\'s|where|when|who|why|how|ماذا|ما|أين|متى|من)\b", n, re.I
        )
        if explicit_fact:
            adjusted = []
            for item in base_intents:
                delta = 0.62 if item.name == "remember_fact" else (-0.45 if item.name == "recall_fact" else -0.10)
                evidence = item.evidence + (("explicit-fact-slot",) if item.name == "remember_fact" else ())
                adjusted.append(IntentCandidate(item.name, max(0.0, min(0.99, item.confidence + delta)), evidence, item.capability, item.required_slots, item.missing_slots, item.source))
            # Ensure the explicit memory capability exists even when the legacy fuzzy
            # router failed to return it at all. This remains deterministic and auditable.
            if not any(item.name == "remember_fact" for item in adjusted):
                adjusted.append(IntentCandidate(
                    "remember_fact", 0.92, ("explicit-fact-slot",), "memory", source="semantic-router"
                ))
            base_intents = sorted(adjusted, key=lambda x: (-x.confidence, x.name))[:10]
        # Volatile domains (weather, news, prices, live data) should not be misrouted
        # to a generic time/date route merely because the surface form is a question.
        # Colloquial small-talk such as "ايه الأخبار" is intentionally not treated as a
        # web-search request unless the user asks to search/find/latest news explicitly.
        # This keeps the retrieval-native semantic layer from turning a social utterance into work.
        if re.fullmatch(r"(?:ايه|إيه)\s+الاخبار", n, re.I):
            base_intents = []

        # Bootstrapped examples provide a weak data-derived prior when the deterministic
        # semantic router is uncertain. They never override explicit typed slots or safety
        # rules and never create executable capabilities by themselves.
        if not base_intents or (base_intents and base_intents[0].confidence < 0.78):
            try:
                base_intents = apply_brain_priors(original, base_intents, registry, speech_act=("question" if re.search(r"^(?:what|what\'s|where|when|who|why|how|ماذا|ما|أين|متى|من|مين|انا مين|أنا مين|ليه|لماذا|ازاي|إزاي)\b", n, re.I) or n.endswith(("?", "؟")) or re.search(r"\b(?:what\s+(?:do\s+you\s+remember|you\s+remember)|what\s+you\s+know)\b", n, re.I) else "request"))
            except Exception:
                pass
        explicit_social = _explicit_social_turn(original)
        if explicit_social:
            social_intents = []
            for item in base_intents:
                if item.name == explicit_social:
                    social_intents.append(IntentCandidate(
                        item.name,
                        min(0.99, max(item.confidence, 0.88) + 0.08),
                        item.evidence + ("explicit-social-turn",),
                        item.capability,
                        item.required_slots,
                        item.missing_slots,
                        "semantic-router",
                    ))
                elif item.name in {"knowledge_query", "web_research", "scientific_research", "open_world_learning", "memory_profile", "recall_fact", "remember_fact"}:
                    social_intents.append(IntentCandidate(
                        item.name,
                        max(0.0, item.confidence - 0.55),
                        item.evidence + ("social-turn-priority",),
                        item.capability,
                        item.required_slots,
                        item.missing_slots,
                        item.source,
                    ))
                else:
                    social_intents.append(item)
            if not any(item.name == explicit_social for item in social_intents):
                social_intents.insert(0, IntentCandidate(explicit_social, 0.92, ("explicit-social-turn",), "social", source="semantic-router"))
            base_intents = sorted(social_intents, key=lambda x: (-x.confidence, x.name))[:10]

        if re.search(r"\b(?:weather|forecast|price|stock|news|live)\b|الطقس|السعر|الأسعار|الاخبار|الأخبار|مباشر", n, re.I):
            adjusted = []
            for item in base_intents:
                delta = 0.40 if item.name == "web_research" else (-0.35 if item.name == "time" else 0.0)
                adjusted.append(IntentCandidate(item.name, max(0.0, min(0.99, item.confidence + delta)), item.evidence + (("fresh-data-context",) if delta else ()), item.capability, item.required_slots, item.missing_slots, item.source))
            base_intents = sorted(adjusted, key=lambda x: (-x.confidence, x.name))[:10]
        # Normalize semantic vocabulary once at the semantic boundary so downstream
        # consumers never have to know legacy intent aliases.
        base_intents = _canonicalize_intent_candidates(base_intents)
        top = base_intents[0] if base_intents else None
        if resolved_reference is not None:
            placeholder_queries = {
                "this", "that", "this task", "that task", "this request", "that request",
                "دي", "ده", "المهمة دي", "المهمة ده", "هذه المهمة", "هذا الطلب", "ذلك الطلب",
            }
            if slots.get("query", "").casefold() in placeholder_queries:
                slots["query"] = str(resolved_reference.target)
        # Explicit skill-selection language is a capability signal of its own. When a
        # task deictic points at a prior goal, preserve the current skill-selection intent
        # instead of allowing the prior goal's fuzzy domain similarity to replace it.
        if resolved_reference is not None and _reference_is_task_deictic(original, str(resolved_reference.text)):
            skill_candidates = [
                item for item in base_intents
                if item.name in {"skill_query", "skill_selection", "skill_discovery"}
                and re.search(r"\b(?:skills?|skill)\b|مهار(?:ة|ات)", n, re.I)
            ]
            if skill_candidates:
                preferred = max(skill_candidates, key=lambda item: (item.confidence, item.name))
                base_intents = [preferred] + [item for item in base_intents if item.name != preferred.name]
                top = preferred

        if resolved_reference is not None and not slots.get("query"):
            referential_intents = {
                "skill_query", "skill_selection", "project_task", "data_analysis",
                "development_validation", "development_inspection", "research",
                "web_research", "scientific_research", "rag_reasoning", "agentic_rag",
                "query_knowledge",
            }
            if top is not None and top.name in referential_intents:
                slots["query"] = str(resolved_reference.target)

        conf = top.confidence if top else 0.0
        if len(base_intents) >= 2 and _confidence_gap(base_intents) < 0.10:
            conf *= 0.82
        safety = []
        if re.search(r"(?:ignore|follow|execute|erase|delete|اقرأ.*واتبع|نفذ.*تعليمات)", original, re.I):
            safety.append("instruction-like-content-in-user-input")
        unresolved = [r for r in references if not r.resolved and (r.confidence >= 0.65 or r.kind in {"pronoun", "prior_object"})]
        ambiguous_smalltalk = bool(re.fullmatch(r"(?:ايه|إيه)\s+(?:الاخبار|الأخبار)", n, re.I))
        # A standalone social turn is a complete conversational act. Tokens such as
        # the "it" in "got it" are not action references and must not force clarification.
        if explicit_social:
            unresolved = []
        needs = bool(unresolved) or ambiguous_smalltalk
        if explicit_social:
            speech_act = "greeting"
        elif re.match(r"^(?:no[, ]+)?(?:i\s+mean|i\s+meant|actually|that\s+isn\'t\s+right|not\s+that|اقصد|أقصد|قصدي|بل|لا)\b", n, re.I):
            speech_act = "correction"
        elif re.match(r"^(?:could|can|would|will|please)\s+you\b", n, re.I) or re.match(r"^(?:ممكن|هل يمكنك|لو سمحت|من فضلك)\b", n, re.I):
            speech_act = "request"
        elif re.search(r"^(?:what|what\'s|where|when|who|why|how|ماذا|ما|أين|متى|من|ليه|لماذا|ازاي|إزاي)\b", n, re.I) or n.endswith(("?", "؟")):
            speech_act = "question"
        elif re.search(r"^(?:my\s+name\s+is|my\s+city\s+is|i\s+prefer|i\s+like|i\s+usually\s+use|i\s+live\s+in|i\s*(?:[\'’]?m|am)\s+from|i\s+come\s+from|i\s+was\s+born\s+in|my\s+language\s+is|اسمي|مدينتي|انا\s+من|أنا\s+من|انا\s+(?:سني|عمري)|انا\s+بفضل|انا\s+احب|انا\s+عادة\s+بستخدم)\b", n, re.I):
            speech_act = "statement"
        elif re.search(r"^(?:please\s+)?(?:do|run|open|save|find|search|calculate|analyze|build|check|remember|forget|delete|erase|remove|احفظ|سجل|ابحث|دور|احسب|حلل|ابني|اختبر|افحص|امسح|انس|انسى|احذف)\b", n, re.I):
            speech_act = "command"
        else:
            speech_act = "request"

        # Cross-language follow-ups often contain only a generic action verb + a resolved
        # reference (e.g. "Check it" / "راجع المهمة دي"). When the local intent is absent
        # or weak and the turn is a command/request, inherit the previous task's semantic
        # route instead of allowing fuzzy similarity to invent a different capability.
        if resolved_reference is not None and last_goal and speech_act in {"command", "request"}:
            try:
                prior_candidates = candidates(last_goal)
                prior_top = prior_candidates[0] if prior_candidates else None
                current_top = base_intents[0] if base_intents else None
                explicit_current_capability = bool(current_top and current_top.name in {
                    "skill_query", "skill_selection", "skill_discovery", "development_git",
                    "development_validation", "development_inspection", "data_analysis",
                })
                if prior_top is not None and (current_top is None or (current_top.confidence < 0.70 and not explicit_current_capability)):
                    carried = IntentCandidate(
                        prior_top.name,
                        max(0.86, prior_top.confidence),
                        prior_top.evidence + ("cross-language-follow-up-context",),
                        prior_top.capability,
                        prior_top.required_slots,
                        prior_top.missing_slots,
                        "context-router",
                    )
                    remaining = [item for item in base_intents if item.name != carried.name]
                    base_intents = [carried] + remaining[:9]
                    top = carried
            except Exception:
                pass
        actionability = "information" if speech_act == "question" else ("correction" if speech_act == "correction" else "action")
        requires_fresh_data = bool(re.search(r"\b(?:today|now|current|latest|newest|recent|weather|price|stock|news|live)\b|\b(?:اليوم|دلوقتي|حالي|احدث|أحدث|جديد|الطقس|السعر|الاخبار|الأخبار|مباشر)\b", n, re.I))
        # Generic factual questions receive a dedicated capability only when no
        # stronger intent already owns the turn. This gives the planner a safe
        # open-world answer path instead of forcing an arbitrary legacy intent.
        top_for_question = base_intents[0] if base_intents else None
        knowledge_candidate = infer_knowledge_question_candidate(
            original, getattr(top_for_question, "name", "") if top_for_question else "",
            float(getattr(top_for_question, "confidence", 0.0) or 0.0) if top_for_question else 0.0,
        )
        if knowledge_candidate is not None:
            name, confidence, evidence, capability = knowledge_candidate
            base_intents.append(IntentCandidate(name, confidence, tuple(evidence), capability, source="answer-policy"))
            base_intents.sort(key=lambda x: (-x.confidence, x.name))
            base_intents = base_intents[:10]
            slots.setdefault("question", original)
        reasons = ["reference-unresolved"] if unresolved else []
        if any((not ref.resolved) and ref.kind in {"pronoun", "prior_object"} for ref in references):
            reasons.append("anaphoric_reference_unresolved")
        domain = (top.capability if top else "general")
        base = SemanticParse(
            original=original,
            normalized=n,
            language=_language(original),
            domain=domain,
            canonical_goal=_canonical_goal(original, slots, speech_act),
            intent_candidates=base_intents,
            entities=entities,
            references=references,
            temporal=temporal,
            constraints=constraints,
            slots=slots,
            required_information=[f"تحديد المقصود من '{unresolved[0].text}'"] if unresolved else (["هل تقصد أخبارًا محددة تريد البحث عنها؟"] if ambiguous_smalltalk else []),
            ambiguity_reasons=(reasons + (["ambiguous-smalltalk"] if ambiguous_smalltalk else [])),
            safety_signals=safety,
            needs_clarification=needs,
            clarification_question=("هل تقصد أخبارًا محددة تريدني أبحث عنها؟" if ambiguous_smalltalk else ("ممكن توضّح المقصود؟" if needs else "")),
            confidence=conf,
            speech_act=speech_act,
            actionability=actionability,
            requires_fresh_data=requires_fresh_data,
            source="deterministic",
        )
        # Language-pattern promotion remains a learned optimization over grounded parses.
        # It does not generate language or execute actions.
        if self.pattern_cache is not None and base.confidence >= 0.72 and not base.needs_clarification:
            try:
                cached = self.pattern_cache.lookup(base)
                if cached is not None:
                    return self.pattern_cache.materialize(base, cached)
            except Exception:
                pass
        base.source = "retrieval-nlp"
        return base


def semantic_understand(goal: str, mem=None, world=None, registry=None,
                        session_id: str | None = None, now: datetime | None = None, pattern_cache=None) -> SemanticParse:
    return SemanticInterpreter(pattern_cache=pattern_cache).parse(goal, mem, world, registry, session_id=session_id, now=now)

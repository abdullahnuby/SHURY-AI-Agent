from __future__ import annotations
from datetime import datetime
import re
from typing import Any, Mapping

from app.intelligence.understanding import normalize, understand
from app.intelligence.language import prepare, detect_language
from app.intelligence.answer_policy import infer_knowledge_question_candidate
from app.knowledge.memory import get_memory
from app.runtime.registry import Tool
from .models import SemanticParse, EntityMention, IntentCandidate, Reference, TemporalExpression, SemanticConstraint
from .intents import ROUTES, candidates
from .entities import extract_entities
from .references import resolve_references, _reference_is_task_deictic
from .temporal import extract_temporal
from .constraints import extract_constraints
from .slots import extract_slots
from app.tools.workspace_reference import extract_workspace_reference, single_workspace_dataset
from .brain_prior import apply_brain_priors
from app.knowledge.memory_query import plan_memory_query

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
    return detect_language(text)


def _tool_intents(registry: dict[str, Tool]) -> set[str]:
    names = {i.name for i in understand("calculate 1+1").intents}
    # Keep existing intent names plus the audited semantic route names. Tool names are
    # not intents; this boundary prevents similarity routing from inventing capabilities.
    names.update({
        "calculate", "time", "save_note", "list_notes", "search_notes", "remember_fact", "recall_fact",
        "recall_last_result", "remember_result", "remember_last_result", "memory_search", "memory_profile", "memory_stats", "remember_memory", "forget_fact", "history",
        "web_research", "scientific_research", "research_memory_search", "open_world_learning", "github_discovery", "github_learning",
        "data_analysis", "data_analysis_report", "research_report", "workspace_reasoning", "workspace_inventory", "project_audit", "development_validation", "development_inspection", "development_learning",
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
        "افتكر", "فاكر", "تفتكر", "قلتلك", "قولتلك", "اللي قلتلك", "اللي قولتلك",
        "امبارح", "مبارح", "قبل كده", "من شوية", "المعلومة اللي", "الرقم اللي",
        "meeting", "appointment", "interview", "booking", "trip", "reminder", "note", "notes",
        "call", "delivery", "visit", "remember", "told you", "yesterday", "before",
    )
    if any(marker in n for marker in memory_markers):
        return question

    # Egyptian/colloquial fact-recall often omits an explicit memory verb and asks
    # directly for a stored datum (e.g. "ما رقم المورد؟", "الكود كان كام؟").
    # This is a semantic shape, not a task-specific name/value rule: it is limited to
    # datum-shaped nouns and question forms, and explicit external-search cues still
    # outrank it later in the parser.
    stored_datum_markers = (
        "الرقم", "رقم", "الكود", "كود", "المعلومة", "المعلومات", "البيانات", "التفاصيل",
        "الاسم", "اسم", "الموعد", "الميعاد", "العنوان", "البريد", "الباسورد",
        "number", "code", "detail", "details", "information", "data", "address", "email",
    )
    return question and any(marker in n for marker in stored_datum_markers)


class SemanticInterpreter:
    def __init__(self, pattern_cache=None):
        self.pattern_cache = pattern_cache

    def parse(self, goal: str, mem=None, world=None, registry: dict[str, Tool] | None = None,
              session_id: str | None = None, now: datetime | None = None) -> SemanticParse:
        original = str(goal or "").strip()
        language_input = prepare(original)
        n = language_input.normalized
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
        if mem is None:
            try: mem = get_memory()
            except Exception: mem = None
        base_intents = candidates(original)
        slots = extract_slots(original)
        memory_stats_request = bool(re.search(
            r"^(?:كم|كام)\s+(?:معلومة|حاجة)(?:\s+مسجلة)?(?:\s+عندك)?[؟?]?$", n, re.I
        ))
        last_result_request = bool(re.fullmatch(
            r"(?:ما(?:\s+هي|\s+هو)?\s+(?:ال)?(?:نتيجة|ناتج)\s+(?:السابقة|السابق)|"
            r"what\s+(?:was|is)\s+(?:the\s+)?(?:previous|last)\s+(?:result|output))[؟?]?",
            n, re.I,
        ))
        generic_anaphoric_imperative = (
            not str(last_goal or '').strip()
            and bool(re.search(r"(?:\b(?:اعمل|نفذ|نفّذ|شغل|شغّل|do|run|execute)\b).*\b(?:كده|كذا|ده|دي|this|that|it)\b", n, re.I))
        )
        underspecified_imperative = generic_anaphoric_imperative or bool(re.fullmatch(
            r"(?:نفذ|نفّذ)\s+(?:الأمر|الامر)|execute\s+the\s+command", n, re.I
        ))
        if generic_anaphoric_imperative:
            base_intents = [
                IntentCandidate('unknown_task', 0.995, ('underspecified-anaphoric-imperative',), 'general', source='semantic-router'),
                *[item for item in base_intents if item.name != 'unknown_task'],
            ]
        if last_result_request:
            slots["result:reference"] = "previous"
            base_intents = [
                IntentCandidate("recall_last_result", 0.99, ("explicit-previous-result-query",), "memory", source="semantic-rule"),
                *(item for item in base_intents if item.name != "recall_last_result"),
            ]
        elif memory_stats_request:
            base_intents = [
                IntentCandidate("memory_stats", 0.99, ("explicit-memory-count-query",), "memory", source="semantic-rule"),
                *(item for item in base_intents if item.name != "memory_stats"),
            ]
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

        # An explicit memory-forget form is authoritative unless the same utterance names
        # a concrete local file/path. This keeps generic Egyptian "forget/delete this fact"
        # language in the memory department instead of drifting to workspace deletion.
        if "forget:key" in slots:
            forget_candidate = str(slots.get("forget:key") or "").strip()
            has_file_like_ref = bool(re.search(r"(?:[\\/]\s*|\.(?:csv|json|txt|md|py|pdf|xlsx?)\b)", forget_candidate, re.I))
            if not has_file_like_ref and not re.search(r"(?:\bworkspace\b|مساحة\s+العمل|مساحة\s+المشروع|مجلد\s+العمل|مجلد\s+المشروع|\bfile\b|\bfolder\b|ملف|مجلد|فولدر|directory|folder)", n, re.I):
                forget_candidate_intent = IntentCandidate(
                    "forget_fact", 0.995, ("explicit-memory-forget-slot",), "forget_fact", source="semantic-router"
                )
                base_intents = [forget_candidate_intent] + [x for x in base_intents if x.name != "forget_fact"]

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
        # Workspace scope is shared by shallow and recursive workspace capabilities.
        has_workspace_scope = bool(re.search(
            r"(?:\bworkspace\b|\bshared\s+workspace\b|مساحة\s+العمل|مساحة\s+المشروع|مجلد\s+العمل|مجلد\s+المشروع)",
            n, re.I,
        ))

        # Content-based duplicate cleanup is a distinct high-risk executable capability.
        # It is selected only when the goal contains content-identity/hash language,
        # duplicate-group reasoning, and a safe archive/retain action.
        has_duplicate_signal = bool(re.search(
            r"(?:duplicate|duplicates|same\s+content|identical\s+content|sha[- ]?256|hash|نسخ?\s+متطابق|المحتوى\s+نفسه|نفس\s+المحتوى|متطابقه|متطابقة|بصمة\s+المحتوى)",
            n, re.I,
        ))
        has_archive_action = bool(re.search(
            r"(?:archive|archiv(?:e|ing)|move\s+.*archive|keep\s+(?:one|a\s+single)|without\s+delet|دون\s+حذف|بدون\s+حذف|انقل.*أرشيف|انقل.*ارشيف|احتفظ\s+بنسخة|نسخة\s+واحدة|النسخ\s+الزائدة)",
            n, re.I,
        ))
        has_duplicate_verification = bool(re.search(
            r"(?:fingerprint|sha[- ]?256|integrity|content\s+.*unchanged|no\s+loss|لم\s+يتغير|سلامة\s+المحتوى|عدم\s+فقد|لا.*استبدال|دون\s+استبدال)",
            n, re.I,
        ))
        if has_workspace_scope and has_duplicate_signal and has_archive_action and has_duplicate_verification:
            base_intents = [
                IntentCandidate(
                    "workspace_duplicate_cleanup", 0.999,
                    ("typed-workspace-duplicate-cleanup-structure",),
                    "workspace_duplicate_cleanup", source="semantic-router",
                ),
                *[item for item in base_intents if item.name not in {
                    "workspace_duplicate_cleanup", "workspace_inventory", "workspace_recursive_inventory",
                    "workspace_file_organization", "workspace_reasoning", "project_audit",
                    "development_inspection", "development_validation", "development_git",
                    "data_analysis", "knowledge_query", "query_knowledge",
                }],
            ][:10]

        # Cross-department sales-analysis/report workflow: choose the CSV whose sales/revenue
        # average is highest, build a report, move that report to a requested report folder,
        # and verify the persisted artifact. This is structurally distinct from moving data.
        has_average_signal = bool(re.search(r"(?:highest\s+average|largest\s+average|top\s+average|أعلى\s+متوسط|أكبر\s+متوسط|أعلى\s+متوسطاً|أعلى\s+متوسطًا|اعلى\s+متوسط|اكبر\s+متوسط)", n, re.I))
        has_sales_revenue_signal = bool(re.search(r"(?:\bsales\b|\brevenue\b|المبيعات|الإيراد|الايراد)", n, re.I))
        has_report_move_destination = bool(re.search(r"(?:selected[_ -]?reports|report[s]?\s+folder|مجلد\s+(?:التقارير|التقرير)|تقارير)", n, re.I))
        has_csv_signal = bool(re.search(r"(?:\bcsv\b|\bCSV\b|ملفات?\s+CSV|ملفات?\s+بيانات)", n, re.I))
        has_report_signal = bool(re.search(r"(?:\breport\b|\bsummary\b|تقرير|ملخص)", n, re.I))
        has_move_signal = bool(re.search(r"(?:\bmove\b|\btransfer\b|\bprocess(?:ed|ing)?\b|نقل|انقل|معالجة)", n, re.I))
        has_verification_signal = bool(re.search(r"(?:verify|verification|fingerprint|hash|integrity|تحقق|بصمة|سلامة|مطابق)", n, re.I))
        if has_workspace_scope and has_csv_signal and has_average_signal and has_sales_revenue_signal and has_report_signal and has_move_signal and has_verification_signal and has_report_move_destination:
            base_intents = [
                IntentCandidate(
                    "cross_department_sales_report_move", 1.0,
                    ("typed-cross-department-sales-average-report-structure",),
                    "cross_department_sales_report_move", source="semantic-router",
                ),
                *[item for item in base_intents if item.name not in {
                    "cross_department_sales_report_move", "cross_department_data_move",
                    "workspace_file_organization", "workspace_inventory", "workspace_recursive_inventory",
                    "data_analysis", "data_analysis_report",
                }],
            ][:10]

        # Cross-department data-to-filesystem workflow: detect a compositional goal from
        # independent structural signals (recursive CSV analysis + comparison + movement + report + verification).
        has_csv_signal = bool(re.search(r"(?:\bcsv\b|\bCSV\b|ملفات?\s+CSV|ملفات?\s+بيانات)", n, re.I))
        has_analysis_signal = bool(re.search(r"(?:analy[sz]e|analysis|compare|total|average|largest|highest|حلل|تحليل|قارن|إجمالي|أكبر)", n, re.I))
        has_move_signal = bool(re.search(r"(?:\bmove\b|\btransfer\b|\bprocess(?:ed|ing)?\b|نقل|انقل|معالجة)", n, re.I))
        has_report_signal = bool(re.search(r"(?:\breport\b|\bsummary\b|تقرير|ملخص)", n, re.I))
        has_verification_signal = bool(re.search(r"(?:verify|verification|fingerprint|hash|integrity|تحقق|بصمة|سلامة|مطابق)", n, re.I))
        if has_workspace_scope and has_csv_signal and has_analysis_signal and has_move_signal and has_report_signal and has_verification_signal:
            base_intents = [
                IntentCandidate(
                    "cross_department_data_move", 0.999,
                    ("typed-cross-department-data-move-structure",),
                    "cross_department_data_move", source="semantic-router",
                ),
                *[item for item in base_intents if item.name not in {
                    "cross_department_data_move", "workspace_file_organization", "workspace_inventory",
                    "workspace_recursive_inventory", "data_analysis", "data_analysis_report"
                }],
            ][:10]

        # Workspace file organization is a compound executable capability.
        # Detect the request from workspace scope + organization/move language rather than one benchmark sentence.
        has_workspace_organization_scope = bool(re.search(
            r"(?:\bworkspace\b|مساحة\s+العمل|مساحة\s+المشروع|مجلد\s+العمل|مجلد\s+المشروع)", n, re.I,
        ))
        has_file_organization_action = bool(re.search(
            r"(?:\b(?:organize|sort|arrange|classify|move)\b|(?<!\w)(?:رتب|نظم|صنف|انقل|تنظيم|ترتيب)(?!\w))", n, re.I,
        ))
        has_file_type_signal = bool(re.search(
            r"(?:\b(?:type|extension|folder|folders|category|categories)\b|النوع|الامتداد|مجلدات|تصنيف)", n, re.I,
        ))
        if has_workspace_organization_scope and has_file_organization_action and (has_file_type_signal or "files" in n.lower() or "الملفات" in n):
            base_intents = [
                IntentCandidate(
                    "workspace_file_organization", 0.998,
                    ("typed-workspace-file-organization-structure",),
                    "workspace_file_organization", source="semantic-router",
                ),
                *[item for item in base_intents
                  if item.name not in {
                      "workspace_file_organization", "workspace_inventory", "workspace_reasoning",
                      "project_audit", "development_inspection", "development_validation", "development_git",
                  }],
            ][:10]

        # Recursive workspace inventory is a distinct executable capability.
        # Prefer it over the legacy shallow inventory whenever the goal explicitly
        # asks for subfolders/recursive inspection and largest-file ranking.
        has_recursive_scope = bool(re.search(
            r"(?:recursive|recursively|subfolders|sub-directories|entire workspace|بما في ذلك المجلدات الفرعية|المجلدات الفرعية|بشكل recursive|بالكامل)",
            n, re.I,
        ))
        has_largest_ranking = bool(re.search(
            r"(?:largest\s+(?:five|5)|top\s*5|biggest\s+(?:five|5)|أكبر\s*5|اكبر\s*5|أكبر خمسة|أكبر الملفات)",
            n, re.I,
        ))
        has_folder_stats = bool(re.search(
            r"(?:per[- ]folder|each folder|folder statistics|عدد الملفات.*كل مجلد|كل مجلد|إجمالي حجم الملفات.*مجلد)",
            n, re.I,
        ))
        if has_workspace_scope and has_recursive_scope and (has_largest_ranking or has_folder_stats):
            base_intents = [
                IntentCandidate(
                    "workspace_recursive_inventory", 0.999,
                    ("typed-workspace-recursive-inventory-structure",),
                    "workspace_recursive_inventory", source="semantic-router",
                ),
                *[item for item in base_intents
                  if item.name not in {
                      "workspace_recursive_inventory", "workspace_inventory", "workspace_reasoning",
                      "project_audit", "development_inspection", "development_validation", "development_git",
                      "data_analysis", "knowledge_query", "query_knowledge",
                  }],
            ][:10]

        # Workspace scope is shared by shallow and recursive workspace capabilities.
        has_workspace_scope = bool(re.search(
            r"(?:\bworkspace\b|\bshared\s+workspace\b|مساحة\s+العمل|مساحة\s+المشروع|مجلد\s+العمل|مجلد\s+المشروع)",
            n, re.I,
        ))

        # Workspace inventory is a simple executable capability.
        # Detect it from the structure of the request rather than from one sentence.
        # A workspace path is the target; listing/enumeration is the requested operation.
        has_inventory_action = bool(re.search(
            r"(?:\binventor(?:y|ies)\b|\blist\b|\benumerate\b|\bfile\s+inventory\b|\blist\s+all\s+files\b|حصر|احصر|جرد|قائمة\s+ملفات)",
            n, re.I,
        ))
        if has_workspace_scope and has_inventory_action:
            base_intents = [
                IntentCandidate(
                    "workspace_inventory", 0.995,
                    ("typed-workspace-inventory-structure",),
                    "workspace_inventory", source="semantic-router",
                ),
                *[item for item in base_intents
                  if item.name not in {
                      "workspace_inventory", "workspace_reasoning", "project_audit",
                      "development_inspection", "development_validation", "development_git",
                      "data_analysis", "knowledge_query", "query_knowledge",
                  }],
            ][:10]

        # Compound project-audit requests are a first-class executable capability.
        # Detect the capability from the structure of the task, not from one benchmark sentence.
        has_project_scope = bool(re.search(
            r"(?:\b(?:project|repository|repo|codebase|workspace)\b|مشروع|المشروع|الريبو|المستودع|الكود)", n, re.I
        ))
        has_project_inspection = bool(re.search(
            r"(?:inspect|analy[sz]e|review|audit|check the project|افحص|راجع|دقق|حلل)", n, re.I
        ))
        has_project_git = bool(re.search(
            r"(?:\bgit\b|git status|repository state|working tree|حالة git|حالة المستودع)", n, re.I
        ))
        has_project_tests = bool(re.search(
            r"(?:\btests?\b|test suite|run the tests|run project tests|build|compile|اختبارات|الاختبارات|اختبر|ابني|البناء|التجميع)", n, re.I
        ))
        has_project_report = bool(re.search(
            r"(?:report|تقرير|recommendations|توصيات|root causes|الأسباب الجذرية|الأسباب|priorit)", n, re.I
        ))
        if has_project_scope and has_project_inspection and (has_project_git or has_project_tests) and has_project_report:
            promoted = []
            for item in base_intents:
                if item.name == "project_audit":
                    promoted.append(item)
                elif item.name in {"development_inspection", "development_validation", "development_git", "knowledge_query", "query_knowledge", "github_learning", "open_world_learning"}:
                    promoted.append(IntentCandidate(
                        item.name, min(item.confidence, 0.20), item.evidence + ("project-audit-structure-demotion",),
                        item.capability, item.required_slots, item.missing_slots, "semantic-router"
                    ))
                else:
                    promoted.append(item)
            if not any(item.name == "project_audit" for item in promoted):
                promoted.append(IntentCandidate(
                    "project_audit", 0.995,
                    ("typed-project-audit-structure",), "project_audit", source="semantic-router"
                ))
            else:
                promoted=[IntentCandidate("project_audit", max(0.995, next(i.confidence for i in promoted if i.name=="project_audit")), ("typed-project-audit-structure",), "project_audit", source="semantic-router") if item.name=="project_audit" else item for item in promoted]
            base_intents = sorted(promoted, key=lambda x: (-x.confidence, x.name))[:10]

        # Compound local data-analysis requests that explicitly create/save a report are
        # a distinct capability. Detect the capability from the typed structure of the
        # request (dataset path + analysis action + report artifact), not from whether the
        # retrieval model happened to return a `data_analysis` candidate first. This prevents
        # fuzzy retrieval noise from turning a concrete executable task into clarification.
        has_dataset_path = bool(re.search(r"[^\s,;!?؟]+\.(?:csv|json|sqlite3?|db)\b", n, re.I))
        has_analysis_action = bool(re.search(
            r"(?:حلل|تحليل|حللاً|حللّ|اكتشف|اكتشفي|determine|analy[sz]e|analy[sz]is|profile|diagnos[ei]?)\b", n, re.I
        ))
        has_report_action = bool(re.search(
            r"(?:report|تقرير|save|write|create|generate|احفظ|اكتب|أنشئ|انشئ)\b", n, re.I
        ))
        has_report_artifact = bool(re.search(r"(?:\.(?:md|txt)\b|تقرير|report)", n, re.I))
        if has_dataset_path and has_analysis_action and has_report_action and has_report_artifact:
            promoted = []
            for item in base_intents:
                if item.name == "data_analysis":
                    promoted.append(IntentCandidate(
                        "data_analysis_report", max(0.97, item.confidence),
                        item.evidence + ("compound-analysis-report-goal", "typed-data-report-structure"),
                        "data_analysis_report", source="semantic-router"
                    ))
                elif item.name in {"knowledge_query", "query_knowledge", "web_research", "open_world_learning", "github_learning", "memory_search"}:
                    promoted.append(IntentCandidate(
                        item.name, min(item.confidence, 0.12),
                        item.evidence + ("typed-data-report-demotion",), item.capability,
                        item.required_slots, item.missing_slots, "semantic-router"
                    ))
                else:
                    promoted.append(item)
            if not any(item.name == "data_analysis_report" for item in promoted):
                promoted.append(IntentCandidate(
                    "data_analysis_report", 0.985,
                    ("typed-data-report-structure",), "data_analysis_report", source="semantic-router"
                ))
            base_intents = sorted(promoted, key=lambda x: (-x.confidence, x.name))[:10]

        # Final typed external-research boundary. A workspace output path is an artifact
        # destination, not project scope. Explicit web/internet + research/papers + report
        # structure must win over fuzzy project-audit retrieval.
        typed_external_research = bool(re.search(r"(?:الإنترنت|الانترنت|الويب|اونلاين|أونلاين|\bonline\b|\binternet\b|\bweb\b)", n, re.I)) and bool(re.search(r"(?:أبحاث|الأبحاث|أوراق|الأوراق|دراسات|research|papers|paper|literature|arxiv|ذاكرة|memory|agents?|وكلاء)", n, re.I))
        if typed_external_research:
            wants_report = bool(re.search(r"(?:تقرير|report|قارن|compare|اختر|choose|أفضل|best|معمار(?:ية|يتين)|architectures?)", n, re.I))
            target = "research_report" if wants_report else "scientific_research"
            existing = next((item for item in base_intents if item.name == target), None)
            base_intents = [
                IntentCandidate(target, max(0.985, existing.confidence if existing else 0.0),
                                tuple(existing.evidence if existing else ()) + ("typed-external-research-final",),
                                ROUTES[target][1], source="semantic-router"),
                *[item for item in base_intents if item.name not in {target, "project_audit", "development_inspection", "development_validation", "development_git", "github_learning"}],
            ][:10]

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
        if last_result_request:
            unresolved = []
        # Direct memory questions are retrieval requests. A discourse pronoun inside the
        # question (for example, a colloquial "اللي قلتلك") should not be reclassified as
        # an unresolved action target; the canonical MemoryController is the authority that
        # decides whether a matching user-owned datum exists. Other action intents keep the
        # strict reference gate.
        memory_intent_names = {
            "memory_search", "recall_fact", "memory_profile", "memory_stats",
            "recall_last_result", "remember_result", "remember_last_result", "forget_fact",
        }
        if base_intents and base_intents[0].name in memory_intent_names:
            unresolved = []
        # A standalone social turn is a complete conversational act. Tokens such as
        # the "it" in "got it" are not action references and must not force clarification.
        if explicit_social:
            unresolved = []
        needs = bool(unresolved) or ambiguous_smalltalk or underspecified_imperative
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
        if memory_stats_request:
            base_intents = [
                IntentCandidate("memory_stats", 0.99, ("explicit-memory-count-query",), "memory", source="semantic-rule"),
                *(item for item in base_intents if item.name not in {"memory_stats", "knowledge_query"}),
            ]
        elif last_result_request:
            base_intents = [
                IntentCandidate("recall_last_result", 0.99, ("explicit-previous-result-query",), "memory", source="semantic-rule"),
                *(item for item in base_intents if item.name != "recall_last_result"),
            ]

        # A validated numeric expression is an executable calculation goal. Reassert this
        # after late fuzzy/question adjustments so memory/knowledge similarity cannot steal
        # a direct calculation that already contains all required operands. A result-name
        # slot still takes precedence because that is the compound calculate+remember route.
        if slots.get("operation:expression") and not slots.get("result:key"):
            base_intents = [
                IntentCandidate(
                    "calculate", 0.995,
                    ("validated-numeric-expression",), "calculate", source="semantic-router"
                ),
                *[item for item in base_intents if item.name != "calculate"],
            ][:10]

        # Final typed capability boundary: duplicate cleanup must remain executable
        # after late fuzzy/question/context adjustments and must never fall back to
        # the weaker inventory capability when its structural requirements are present.
        if has_workspace_scope and has_duplicate_signal and has_archive_action and has_duplicate_verification:
            base_intents = [
                IntentCandidate(
                    "workspace_duplicate_cleanup", 0.999,
                    ("typed-workspace-duplicate-cleanup-structure-final",),
                    "workspace_duplicate_cleanup", source="semantic-router",
                ),
                *[item for item in base_intents if item.name != "workspace_duplicate_cleanup"],
            ][:10]

        if has_workspace_scope and has_csv_signal and has_analysis_signal and has_move_signal and has_report_signal and has_verification_signal:
            base_intents = [
                IntentCandidate(
                    "cross_department_data_move", 0.999,
                    ("typed-cross-department-data-move-structure-final",),
                    "cross_department_data_move", source="semantic-router",
                ),
                *[item for item in base_intents if item.name != "cross_department_data_move"],
            ][:10]

        if has_workspace_scope and has_csv_signal and has_average_signal and has_sales_revenue_signal and has_report_signal and has_move_signal and has_verification_signal and has_report_move_destination:
            base_intents = [
                IntentCandidate(
                    "cross_department_sales_report_move", 1.0,
                    ("typed-cross-department-sales-average-report-structure-final",),
                    "cross_department_sales_report_move", source="semantic-router",
                ),
                *[item for item in base_intents if item.name not in {"cross_department_sales_report_move", "cross_department_data_move"}],
            ][:10]

        # Final typed capability boundary: recursive workspace inventory remains executable
        # after late question/context adjustments.
        if has_workspace_scope and has_recursive_scope and (has_largest_ranking or has_folder_stats):
            base_intents = [
                IntentCandidate(
                    "workspace_recursive_inventory", 0.999,
                    ("typed-workspace-recursive-inventory-structure-final",),
                    "workspace_recursive_inventory", source="semantic-router",
                ),
                *[item for item in base_intents if item.name != "workspace_recursive_inventory"],
            ][:10]

        # Local workspace references and executable data/file actions are source-typed at the
        # semantic boundary. This prevents generic knowledge/research routing from outranking
        # a concrete local task. Resolution is against the live workspace, never by substring.
        external_explicit = bool(re.search(
            r"(?:search\s+(?:the\s+)?(?:web|internet|online)|ابحث\s+(?:على|في)\s+(?:الويب|الانترنت|الإنترنت)|دور\s+على\s+(?:الويب|الانترنت|الإنترنت)|اونلاين|أونلاين)",
            n, re.I,
        ))
        memory_recall_intent = bool(base_intents) and base_intents[0].name in {
            "memory_search", "recall_fact", "memory_profile", "memory_stats",
            "recall_last_result", "remember_result", "remember_last_result", "forget_fact",
        }
        local_action = bool(re.search(
            r"(?:احسب|اجمع|حلل|اقرا|اقرأ|اقرء|افحص|جرد|احصر|عد|كام|كم|اربط|قارن|راجع|شيك|شيّك|بص|شوف|فتش|افتح|اعمل\s+بروفايل|count|calculate|sum|read|analy[sz]e|inspect|count|join|compare|profile|inventory|enumerate)",
            n, re.I,
        )) and not memory_recall_intent
        move_action = bool(re.search(
            r"(?:انقل|انقلّه|انقلها|نقل|حرك|حرّك|move|transfer|put)\b", n, re.I,
        ))
        source_ref = None if external_explicit else extract_workspace_reference(original, expected_kind='any', role='source')
        destination_ref = None if external_explicit else extract_workspace_reference(original, expected_kind='dir', role='destination')
        # Reference safety is computed before the final reason list is assembled below.
        # Keep a local accumulator so a destination-only boundary violation cannot touch an
        # uninitialized variable.
        reasons: list[str] = []
        if source_ref is not None:
            if source_ref.status == 'outside':
                safety.append('workspace_reference_outside_boundary')
                reasons = ['workspace_reference_outside_boundary']
            elif source_ref.resolved:
                slots.setdefault('path', source_ref.value)
            elif source_ref.status == 'ambiguous':
                reasons = ['workspace_reference_ambiguous']
            if source_ref.status in {'ambiguous', 'outside'}:
                needs = True

        if destination_ref is not None:
            if destination_ref.status == 'outside':
                safety.append('workspace_destination_outside_boundary')
                reasons = list(dict.fromkeys(reasons + ['workspace_destination_outside_boundary']))
                needs = True
            elif destination_ref.resolved:
                slots.setdefault('destination_dir', destination_ref.value)
            elif move_action and destination_ref.status == 'ambiguous':
                reasons = list(dict.fromkeys(reasons + ['destination_ambiguous']))
                needs = True

        # A strongly typed semantic-router workflow already owns the turn; generic local
        # source typing must not demote that structured capability to a broad inventory route.
        strong_typed_intent = bool(
            base_intents
            and base_intents[0].source == 'semantic-router'
            and float(base_intents[0].confidence or 0.0) >= 0.999
        )
        if not external_explicit and not any(k.startswith('operation:expression') for k in slots) and not move_action and not strong_typed_intent:
            local_source = source_ref.value if source_ref is not None and source_ref.resolved else ''
            if not local_source and local_action:
                local_source = single_workspace_dataset() or ''
                if local_source:
                    slots.setdefault('path', local_source)
            if local_action and (local_source or bool(re.search(r"(?:جرد|احصر|inventory|enumerate|list\s+files|كام\s+ملف|كم\s+ملف|عدد\s+الملفات|count\s+files|workspace|مساحة\s+العمل|المجلد)", n, re.I))):
                # Local dataset/file actions take precedence over generic knowledge candidates.
                lowered_local = n.casefold()
                recursive_local = bool(re.search(r"(?:recursive|recursively|subfolders|المجلدات\s+الفرعية|بشكل\s+recursive)", lowered_local, re.I))
                if recursive_local or bool(re.search(r"(?:جرد|احصر|inventory|enumerate|list\s+files|كام\s+ملف|كم\s+ملف|عدد\s+الملفات|count\s+files)", lowered_local, re.I)):
                    target_intent = 'workspace_recursive_inventory' if recursive_local else 'workspace_inventory'
                    base_intents = [IntentCandidate(target_intent, 0.998, ('typed-local-workspace-action',), target_intent, source='semantic-router'), *[i for i in base_intents if i.name != target_intent]][:10]
                elif bool(re.search(r"(?:اقرا|اقرأ|اقرء|count\s+lines|عدد\s+السطور|كام\s+سطر|كم\s+سطر|read\s+the\s+file)", lowered_local, re.I)) and local_source:
                    base_intents = [IntentCandidate('file_read', 0.997, ('typed-local-file-read',), 'file_read', source='semantic-router'), *[i for i in base_intents if i.name != 'file_read']][:10]
                elif local_source:
                    base_intents = [IntentCandidate('data_analysis', 0.998, ('typed-local-data-action',), 'data_analysis', source='semantic-router'), *[i for i in base_intents if i.name != 'data_analysis']][:10]
        if move_action and source_ref is not None and source_ref.resolved:
            base_intents = [IntentCandidate('workspace_file_organization', 0.999, ('typed-file-move-with-destination',), 'workspace_file_organization', source='semantic-router'), *[i for i in base_intents if i.name != 'workspace_file_organization']][:10]
        if source_ref is not None and source_ref.status == 'ambiguous':
            candidates_text = ' ولا '.join(source_ref.candidates[:4])
            slots['workspace:ambiguity_candidates'] = candidates_text
        if destination_ref is not None and destination_ref.status == 'ambiguous':
            slots['workspace:destination_candidates'] = ' ولا '.join(destination_ref.candidates[:4])

        if not any(k.startswith('operation:expression') for k in slots):
            report_requested = bool(re.search(r"(?:تقرير|report|اكتب\s+التقرير|احفظ\s+التقرير|انشئ\s+التقرير|أنشئ\s+التقرير)", n, re.I))
            if report_requested:
                report_matches = list(re.finditer(r'[^\s,;!?؟]+\.(?:md|txt)\b', original, re.I))
                if report_matches:
                    slots.setdefault('output_path', report_matches[-1].group(0).strip(' \t,.;!?؟'))
                # A concrete local dataset + explicit report request is an analysis-report goal,
                # not a generic analysis goal. Preserve the user's destination slot for execution.
                if local_action and not external_explicit and source_ref is not None and source_ref.resolved:
                    base_intents = [
                        IntentCandidate('data_analysis_report', 0.999, ('typed-local-analysis-report',), 'data_analysis_report', source='semantic-router'),
                        *[item for item in base_intents if item.name != 'data_analysis_report'],
                    ][:10]

        # Final typed capability boundary: compound project audits are executable goals.
        # Re-assert this after all fuzzy/question/context adjustments so a late retrieval
        # candidate can never demote an otherwise explicit project-audit structure.
        if has_project_scope and has_project_inspection and (has_project_git or has_project_tests) and has_project_report:
            base_intents = [
                IntentCandidate(
                    "project_audit",
                    0.995,
                    ("typed-project-audit-structure-final",),
                    "project_audit",
                    source="semantic-router",
                ),
                *[item for item in base_intents if item.name != "project_audit"],
            ][:10]
            top = base_intents[0]
        top = base_intents[0] if base_intents else None
        conf = top.confidence if top else 0.0
        reasons = ["reference-unresolved"] if unresolved else []
        anaphoric_unresolved = any((not ref.resolved) and ref.kind in {"pronoun", "prior_object"} for ref in references)
        # Memory recall is itself an explicit request to consult prior user-owned context.
        # A phrase such as "المعلومة اللي خزنتها" may contain a discourse reference, but
        # requiring a separate clarification here would block the memory subsystem from
        # answering "لا توجد معلومة محفوظة" when no matching fact exists. Other operations
        # keep the strict anaphora gate.
        memory_intents = {"memory_search", "recall_fact", "memory_profile", "memory_stats", "recall_last_result", "remember_result", "remember_last_result", "forget_fact"}
        if anaphoric_unresolved and not (top and top.name in memory_intents):
            reasons.append("anaphoric_reference_unresolved")
        custom_reason_set = set(reasons)
        custom_reason_set.update(reason for reason in safety if reason.startswith('workspace_'))
        if source_ref is not None and source_ref.status == 'ambiguous':
            custom_reason_set.add('workspace_reference_ambiguous')
        if destination_ref is not None and destination_ref.status == 'ambiguous' and move_action:
            custom_reason_set.add('destination_ambiguous')
        reasons = sorted(custom_reason_set)
        if any(reason in reasons for reason in {'workspace_reference_ambiguous', 'destination_ambiguous', 'workspace_reference_outside_boundary', 'workspace_destination_outside_boundary'}):
            needs = True
        domain = (top.capability if top else "general")
        memory_plan = plan_memory_query(
            original,
            intent=(top.name if top else ""),
            slots=slots,
            entities=entities,
            references=references,
        )
        if unresolved:
            required_information = [f"تحديد المقصود من '{unresolved[0].text}'"]
        elif ambiguous_smalltalk:
            required_information = ["هل تقصد أخبارًا محددة تريد البحث عنها؟"]
        elif underspecified_imperative:
            required_information = ["تحديد الأمر المطلوب تنفيذه"]
        elif 'workspace_reference_ambiguous' in reasons:
            required_information = ["اختيار ملف/مجلد من المرشحين"]
        elif 'destination_ambiguous' in reasons:
            required_information = ["تحديد مجلد الوجهة من المرشحين"]
        elif source_ref is not None and source_ref.status == 'missing' and local_action and (not top or top.name not in {
            'workspace_inventory', 'workspace_recursive_inventory', 'calculate', 'forget_fact', 'remember_fact', 'remember_memory',
            'remember_result', 'remember_last_result',
        }):
            required_information = ["تحديد ملف أو مجلد محلي موجود فعلًا"]
        else:
            required_information = []

        ambiguity_reasons = tuple(dict.fromkeys(reasons + (["ambiguous-smalltalk"] if ambiguous_smalltalk else []) + (["underspecified-imperative"] if underspecified_imperative else [])))
        if ambiguous_smalltalk:
            clarification_question = "هل تقصد أخبارًا محددة تريدني أبحث عنها؟"
        elif underspecified_imperative:
            clarification_question = "ما الأمر الذي تريدني أن أنفذه؟"
        elif 'workspace_reference_ambiguous' in reasons:
            clarification_question = f"تقصد {slots.get('workspace:ambiguity_candidates')}؟"
        elif 'destination_ambiguous' in reasons:
            clarification_question = f"مجلد الوجهة تقصد {slots.get('workspace:destination_candidates')}؟"
        elif 'workspace_reference_outside_boundary' in reasons or 'workspace_destination_outside_boundary' in reasons:
            clarification_question = "المسار المطلوب خارج الـworkspace المسموح به، فمش هقدر أنفذه."
        elif source_ref is not None and source_ref.status == 'missing' and local_action and (not top or top.name not in {'workspace_inventory', 'workspace_recursive_inventory'}):
            clarification_question = "حدّد اسم الملف أو المجلد المحلي اللي أشتغل عليه."
        else:
            clarification_question = "ممكن توضّح المقصود؟" if needs else ""

        base = SemanticParse(
            original=original,
            normalized=n,
            language=language_input.language,
            language_variant=language_input.variant,
            domain=domain,
            canonical_goal=_canonical_goal(original, slots, speech_act),
            intent_candidates=base_intents,
            entities=entities,
            references=references,
            temporal=temporal,
            constraints=constraints,
            slots=slots,
            required_information=required_information,
            ambiguity_reasons=ambiguity_reasons,
            safety_signals=safety,
            needs_clarification=needs,
            clarification_question=clarification_question,
            confidence=conf,
            speech_act=speech_act,
            actionability=actionability,
            requires_fresh_data=requires_fresh_data,
            source="deterministic",
            memory_need=memory_plan.need,
            memory_types=tuple(memory_plan.memory_types),
            memory_reason=memory_plan.rationale,
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

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .models import Reference

REF_PATTERNS = [
    (r"\b(?:the\s+)?(?:last|previous)\s+result\b|\b(?:the\s+)?previous\s+output\b|\bالنتيجة\s+(?:السابقة|اللي فاتت)\b", "last_result"),
    (r"\b(?:the\s+)?last\s+(?:one|thing)\b|\b(?:اللي فات|السابق|نفسه|نفسها|itself|themselves)\b", "prior_object"),
    (r"\b(?:it|itself|that|this|they|them|themselves|he|she)\b|\b(?:هو|هي|هم|ده|دي|هذا|هذه|هؤلاء|ذلك|تلك|نفسه|نفسها|ده اللي|دي اللي)\b", "pronoun"),
    (r"\bthe\s+(?:report|file|project|document|repository|repo|dataset|papers?|articles?)\b|\b(?:التقرير|الملف|المشروع|المستند|المستودع|البيانات|الأبحاث|الأوراق)\s+(?:ده|السابق|اللي فات)?\b", "definite_entity"),
]

_LOCAL_ANTE = [
    (r"\b(?:papers?|articles?|reports?|files?|documents?|projects?|repositories|repository|repos?|datasets?|results?|outputs?|paper|article|report|file|document|project|repository|repo|dataset|result|output)\b", "local_antecedent"),
    (r"(?:(?<![\w\u0600-\u06ff])|(?<=[وف]))(?:بحث|البحث|بحوث|البحوث|أبحاث|الأبحاث|تقرير|التقرير|تقارير|التقارير|ملف|الملف|ملفات|الملفات|مشروع|المشروع|مشاريع|المشاريع|مستند|المستند|مستندات|المستندات|مستودع|المستودع|مستودعات|المستودعات|ورقة|الورقة|أوراق|الأوراق|بيانات|البيانات|نتيجة|النتيجة|نتائج|النتائج|مخرج|المخرج|مخرجات|المخرجات)\b", "local_antecedent"),
]
_TASK_ANTE = [
    (r"\b(?:task|request|job|assignment|mission|query|problem|matter)\b|\b(?:المهمة|الطلب|الشغل|المطلوب|الاستفسار|المشكلة|الموضوع)\b", "task_antecedent"),
]
_PERSON_ANTE = [
    (r"(?:my\s+(?:brother|father|son)|(?:my\s+)?brother|(?:my\s+)?father|(?:my\s+)?son|اخويا|أخويا|اخي|أخي|والدي|ابويا|أبويا|ابني)\s+(?:is|was|اسمه|هو)\s+([A-Za-z][A-Za-z'-]{1,30}|[\u0600-\u06ff]{2,30})", "person_male"),
    (r"(?:my\s+(?:sister|mother|daughter)|(?:my\s+)?sister|(?:my\s+)?mother|(?:my\s+)?daughter|اختي|أختي|والدتي|امي|أمي|ابنتي)\s+(?:is|was|اسمها|هي)\s+([A-Za-z][A-Za-z'-]{1,30}|[\u0600-\u06ff]{2,30})", "person_female"),
    (r"(?:my\s+name\s+is|my\s+name\s*[:=]|اسمي(?:\s+هو)?\s*[:=]?)\s+([A-Za-z][A-Za-z'-]{1,30}|[\u0600-\u06ff]{2,30})", "person_unknown"),
]
_FORWARD_ANTE = r"\s+(?:the\s+|a\s+|an\s+|ال)?(?:(?:github|gitlab)\s+)?(?:report|file|project|document|repository|repo|dataset|paper|papers|article|articles|reports|files|projects|documents|repositories|الملف|التقرير|المشروع|المستند|المستودع|البيانات|الأبحاث|الأوراق)\b(?:\s+(?!(?:for|about|with|on|in|to|from|before|after|then)\b)[A-Za-z0-9_-]+)?"


@dataclass(frozen=True)
class _Candidate:
    text: str
    source: str
    distance: int = 0
    start: int = -1
    category: str = "object"


def _world_value(world: Any, key: str, default: Any = None) -> Any:
    if isinstance(world, Mapping):
        return world.get(key, default)
    return getattr(world, key, default)


def _find_candidates(text: str, start: int = 0, *, include_tasks: bool = True) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    patterns = [(pat, kind, "object") for pat, kind in _LOCAL_ANTE]
    if include_tasks:
        patterns.extend((pat, kind, "task") for pat, kind in _TASK_ANTE)
    patterns.extend((pat, kind, kind.replace("_antecedent", "")) for pat, kind in _PERSON_ANTE)
    for pat, _kind, category in patterns:
        for match in re.finditer(pat, text[:start], re.I):
            raw = (match.group(1) if match.lastindex else match.group(0)).strip(" ,.;!?؟")
            if raw:
                candidates.append(_Candidate(raw, "same-utterance", start - match.start(), match.start(), category))
    dedup: dict[str, _Candidate] = {}
    for item in sorted(candidates, key=lambda c: (c.start, c.distance)):
        dedup.setdefault(item.text.casefold(), item)
    return list(dedup.values())


def _previous_turn_candidates(recent_episodes: list[dict] | None) -> list[_Candidate]:
    out: list[_Candidate] = []
    for turn_index, episode in enumerate(recent_episodes or []):
        text = str(episode.get("user_text") or "").strip()
        if not text:
            continue
        found = _find_candidates(text, len(text))
        for candidate in found:
            out.append(_Candidate(candidate.text, "previous-turn", turn_index, candidate.start, candidate.category))
        if found:
            # The most recent previous turn with usable antecedents dominates older turns.
            return out
    return out


def _has_forward_antecedent(text: str, end: int) -> tuple[bool, str]:
    match = re.match(_FORWARD_ANTE, text[end:], re.I)
    if not match:
        return False, ""
    raw = re.sub(r"^\s+", "", match.group(0)).strip(" ,.;!?؟")
    return bool(raw), raw


_PROSPECTIVE_ARTIFACT_VERBS = re.compile(
    r"(?:\b(?:create|generate|produce|write|save|make|prepare)\b|"
    r"(?:أنشئ|انشئ|اعمل|اكتب|احفظ|جهز|جهّز|أنشأ|انشأ))", re.I,
)
_PROSPECTIVE_ARTIFACT_NOUNS = re.compile(
    r"(?:report|file|document|dataset|تقرير|ملف|مستند|وثيقة|بيانات)", re.I,
)
_PROSPECTIVE_FILE_TOKEN = re.compile(
    r"(?:[A-Za-z]:[\\/] |/)?[^\s,;!?؟]+\.(?:md|txt|json|csv|xlsx|pdf)\b", re.I | re.X
)

def _prospective_artifact_reference(text: str, start: int, raw: str) -> tuple[str, float, str, bool]:
    """Ground references to artifacts that the same user goal explicitly creates earlier.

    A compound request may say "create a report ... then review the report". The second
    occurrence is prospective plan state, not an unresolved discourse anaphor. Treating it
    as unresolved incorrectly aborts otherwise concrete multi-step goals before planning.
    """
    prefix = text[:start]
    if not _PROSPECTIVE_ARTIFACT_VERBS.search(prefix) or not _PROSPECTIVE_ARTIFACT_NOUNS.search(prefix):
        return "", 0.30, "no prospective artifact declaration", False
    future_files = [m.group(0).strip(" \t,.;!?؟") for m in _PROSPECTIVE_FILE_TOKEN.finditer(text[start:])]
    prior_files = [m.group(0).strip(" \t,.;!?؟") for m in _PROSPECTIVE_FILE_TOKEN.finditer(prefix)]
    if future_files:
        return future_files[0], 0.96, "prospective artifact path follows an explicit creation/save action", True
    if prior_files:
        return prior_files[-1], 0.95, "prospective artifact explicitly declared earlier in the same goal", True
    return raw, 0.86, "prospective artifact explicitly created earlier in the same goal", True


def _is_discourse_connective(text: str, match_start: int, raw: str) -> bool:
    prefix = text[:match_start].rstrip()
    if raw.casefold() == "ذلك" and re.search(r"(?:^|\s)[وف]?بعد$", prefix, re.I):
        return True
    if raw.casefold() == "that" and re.search(r"(?:after|then|and then)$", prefix, re.I):
        return True
    return False


def _reference_is_task_deictic(text: str, raw: str) -> bool:
    if raw.casefold() in {"this", "that"} and re.search(r"\b(?:this|that)\s+(?:task|request|job|assignment|mission|query|problem)\b", text, re.I):
        return True
    return bool(re.search(r"\b(?:ال|لل|بال)?(?:مهمة|طلب|مطلوب|شغل|استفسار|مشكلة|موضوع)\s+(?:دي|ده|هذه|هذا|السابق)\b", text, re.I))


def _nearest_reflexive_noun(text: str, start: int, raw: str) -> str | None:
    """Resolve a reflexive used as a noun-phrase modifier, e.g. 'التقرير نفسه'.

    A phrase like 'the report itself' / 'التقرير نفسه' is locally grounded by the noun
    immediately preceding the reflexive. It is not the same kind of free discourse
    anaphora as 'راجع هذا' or 'عدله', so it should not make a concrete task ambiguous.
    """
    prefix = text[:start]
    if raw.casefold() in {"نفسه", "نفسها"}:
        match = re.search(r"([\u0600-\u06ff]{2,})\s+$", prefix)
    elif raw.casefold() in {"itself", "themselves"}:
        match = re.search(r"(?:the|a|an)\s+([A-Za-z][A-Za-z0-9_-]*)\s+$", prefix, re.I)
    else:
        return None
    if not match:
        return None
    noun = match.group(1).strip()
    if noun in {"هو", "هي", "هم", "ده", "دي", "هذا", "هذه"}:
        return None
    return noun


def _is_plural_reference(raw: str) -> bool:
    return raw.casefold() in {"they", "them", "هم", "هما", "هن", "هؤلاء", "them"}


def _is_generic_deictic(raw: str) -> bool:
    return raw.casefold() in {"it", "that", "this", "he", "she", "هو", "هي", "هم", "هما", "هن", "ه", "ها", "ده", "دي", "هذا", "هذه", "ذلك", "تلك", "نفسه", "نفسها"}


def _goal_can_be_reference(goal: str) -> bool:
    goal = str(goal or "").strip()
    if not goal:
        return False
    return not bool(re.match(
        r"^(?:what|what's|where|when|who|why|how|can|could|is|are|do|does|did|ماذا|ما|أين|متى|من|مين|ليه|لماذا|هل)\b",
        goal, re.I,
    ))


def _pick_unique(candidates: list[_Candidate], raw: str) -> tuple[str, float, str, bool]:
    if not candidates:
        return "", 0.30, "no grounded antecedent", False

    normalized = raw.casefold()
    if normalized in {"he", "she", "هو", "هي"}:
        wanted_category = "person_male" if normalized in {"he", "هو"} else "person_female"
        person = [c for c in candidates if c.category == wanted_category]
        if not person:
            return "", 0.30, "no grounded gender-compatible person antecedent", False
        if len(person) > 1:
            return "", 0.25, "multiple gender-compatible person antecedents", False
        chosen = person[0]
        return chosen.text, 0.91, "gender-compatible person antecedent", True

    # A generic singular pronoun must not silently choose between two same-turn objects.
    same_turn = [c for c in candidates if c.source == "same-utterance"]
    if _is_generic_deictic(raw) and len(same_turn) > 1:
        return "", 0.25, "multiple same-utterance antecedents", False
    contextual = [c for c in candidates if c.source in {"previous-turn", "previous-goal-entity"}]
    if _is_generic_deictic(raw) and len(contextual) > 1:
        return "", 0.25, "multiple contextual antecedents", False

    # Plural references require a grounded plural/object-group candidate. A single noun
    # candidate can still be plural in form (papers, reports, etc.).
    if _is_plural_reference(raw) and len(same_turn) > 1:
        return "", 0.25, "multiple candidate antecedents for plural reference", False

    chosen = same_turn[0] if same_turn else candidates[0]
    if chosen.source == "same-utterance":
        return chosen.text, 0.95, "same-utterance antecedent", True
    if chosen.source == "previous-goal-entity":
        return chosen.text, 0.88, "previous-goal antecedent", True
    if chosen.source == "previous-goal":
        return chosen.text, 0.84, "previous-goal discourse context", True
    return chosen.text, 0.83, "previous-turn antecedent", True


_ARABIC_OBJECT_CLITIC_ACTION_STEMS = {
    "احفظ", "حفظ", "راجع", "أنشئ", "انشئ", "أنشأ", "انشأ", "اكتب", "كتب",
    "اقرأ", "اقرا", "افتح", "حلل", "حلّل", "افحص", "احسب", "ابحث", "قارن",
    "نفذ", "نفّذ", "شغل", "شغّل", "احذف", "امسح", "عدّل", "عدل", "اعرض",
    "استخرج", "اجمع", "رتب", "رتّب", "صنّف", "صنف", "جهز", "جهّز", "خزّن", "خزن",
    "سجل", "سجّل", "انقل", "انقل", "حل", "راجع",
}

def _looks_like_action_with_object_clitic(stem: str) -> bool:
    value = str(stem or "").casefold()
    return any(value.startswith(prefix.casefold()) for prefix in _ARABIC_OBJECT_CLITIC_ACTION_STEMS)


_ARABIC_CLITIC_FALSE_POSITIVES = {
    "عنده", "عندها", "عندهم", "معه", "معها", "معهم", "فيه", "فيها", "فيهم",
    "منه", "منها", "منهم", "عليه", "عليها", "عليهم", "ليه", "بيها", "بيهم",
    "كده", "كذا", "نفسه", "نفسها",
}


def _attached_arabic_pronouns(text: str, *, protected_tokens: set[str] | None = None) -> list[tuple[str, int, int]]:
    found = []
    protected = {str(item or '').strip().casefold() for item in (protected_tokens or set()) if str(item or '').strip()}
    for match in re.finditer(r"\b(?P<stem>[\u0600-\u06ff]{3,})(?P<clitic>هما|هم|ها|هن|ه)\b", text):
        token = match.group(0)
        if token.casefold() in protected:
            continue
        if token in _ARABIC_CLITIC_FALSE_POSITIVES:
            continue
        stem = match.group("stem").lstrip("وف")
        if not _looks_like_action_with_object_clitic(stem):
            continue
        found.append((match.group("clitic"), match.start(), match.end()))
    return found


def resolve_references(text: str, world: dict | object | None = None,
                       recent_episodes: list[dict] | None = None,
                       protected_tokens: set[str] | None = None) -> list[Reference]:
    world = world or {}
    out: list[Reference] = []
    previous_turn = _previous_turn_candidates(recent_episodes)
    last_goal = str(_world_value(world, "last_goal", "") or "").strip()
    previous_goal_entities = [
        _Candidate(item.text, "previous-goal-entity", item.distance, item.start, item.category)
        for item in _find_candidates(last_goal, len(last_goal))
    ]
    last_outputs = _world_value(world, "last_outputs", {}) or {}
    last_result = _world_value(world, "last_result", None)

    for pattern, kind in REF_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            raw = match.group(0).strip()

            # Arabic demonstratives can function as determiners inside an ordinary
            # noun phrase (e.g. "هذا الحصر", "هذه القائمة", "ذلك الملف"). In that
            # construction the demonstrative itself is not a standalone anaphoric
            # reference that requires a previous discourse antecedent. A separate
            # definite-entity pass can still ground the noun phrase when needed.
            if kind == "pronoun" and raw.casefold() in {
                "هذا", "هذه", "ذلك", "تلك", "ده", "دي"
            }:
                tail = text[match.end():]
                if re.match(r"\s+ال[\u0600-\u06ff]{2,}\b", tail):
                    continue

            # Reflexives bound inside a noun phrase (e.g. "التقرير نفسه" / "the report
            # itself") are locally grounded by the noun immediately before them. They do
            # not require a previous-turn antecedent and must not block an otherwise
            # concrete multi-step goal.
            if kind in {"pronoun", "prior_object"}:
                reflexive_target = _nearest_reflexive_noun(text, match.start(), raw)
                if reflexive_target:
                    out.append(Reference(
                        raw, "pronoun", reflexive_target, True, 0.97,
                        basis="same-phrase reflexive noun binding",
                    ))
                    continue

            # In Arabic copular questions, "هو/هي" is grammatical linking
            # rather than discourse anaphora (for example, "ما هو ...؟").
            # Do not manufacture unresolved reference state for that construction.
            if kind == "pronoun" and raw.casefold() in {"هو", "هي"} and re.search(
                r"(?:^|\s)(?:ما|ماذا|ايه|إيه)\s+(?:هو|هي)\b", text, re.I
            ):
                continue

            # Discourse connectives / acknowledgements are not object references.
            if _is_discourse_connective(text, match.start(), raw):
                continue
            if kind == "pronoun" and raw.casefold() == "that" and re.match(
                r"(?:remember|save|store|note)\s+that\b", text[:match.end()], re.I
            ):
                continue
            if kind == "pronoun" and raw.casefold() == "this" and re.search(
                r"(?:save|store|remember)\s+(?:this|that)\s+(?:information|fact|detail)\b", text, re.I
            ):
                continue

            # English "it" can be expletive (e.g. "what time is it?").
            if kind == "pronoun" and raw.casefold() == "it" and re.search(
                r"\b(?:what|when|where|who|why|how)\b.+\bit\b", text, re.I | re.S
            ):
                continue

            target = ""
            confidence = 0.30
            basis = "no grounded antecedent"
            resolved = False

            if kind == "last_result":
                target = "last_result"
                if last_result is not None:
                    confidence, basis, resolved = 0.98, "session last_completed_output", True
                elif isinstance(last_outputs, Mapping) and last_outputs.get("last_result") is not None:
                    confidence, basis, resolved = 0.98, "session last_completed_output", True
                else:
                    confidence, basis = 0.96, "well-defined reference but no result in current session"

            elif kind == "prior_object":
                candidates = list(previous_goal_entities)
                if not candidates and last_goal:
                    candidates.append(_Candidate(last_goal, "previous-goal"))
                candidates.extend(previous_turn)
                target, confidence, basis, resolved = _pick_unique(candidates, raw)
                if resolved and basis == "previous-turn antecedent" and last_goal:
                    # Prefer the exact active goal when the discourse marker explicitly means
                    # the previous task/object as a whole.
                    target, confidence, basis = last_goal, 0.90, "previous-goal discourse context"

            elif kind == "pronoun":
                if _reference_is_task_deictic(text, raw):
                    if _goal_can_be_reference(last_goal):
                        target, confidence, basis, resolved = last_goal, 0.99, "previous-goal discourse context", True
                    else:
                        confidence, basis = 0.97, "task deictic without prior task context"
                else:
                    forward_ok, forward_raw = _has_forward_antecedent(text, match.end())
                    if forward_ok and raw.casefold() in {"this", "that", "these", "those", "ده", "دي", "هذا", "هذه", "ذلك", "تلك"}:
                        target, confidence, basis, resolved = forward_raw, 0.94, "same-utterance forward antecedent", True
                    else:
                        local = _find_candidates(text, match.start())
                        candidates = list(local)
                        if not candidates:
                            candidates.extend(previous_turn)
                        if not candidates:
                            candidates.extend(previous_goal_entities)
                        if not candidates and _goal_can_be_reference(last_goal):
                            candidates.append(_Candidate(last_goal, "previous-goal"))
                        target, confidence, basis, resolved = _pick_unique(candidates, raw)

            elif kind == "definite_entity":
                prospective_target, prospective_confidence, prospective_basis, prospective_resolved = _prospective_artifact_reference(
                    text, match.start(), raw
                )
                if prospective_resolved:
                    target, confidence, basis, resolved = (
                        prospective_target, prospective_confidence, prospective_basis, True
                    )
                    out.append(Reference(raw, kind, target, resolved, confidence, basis=basis))
                    continue
                target = raw
                prior_goal = last_goal.casefold()
                grounded = any(token in prior_goal for token in (
                    "report", "file", "project", "document", "repository", "repo", "dataset",
                    "تقرير", "ملف", "مشروع", "مستند", "مستودع", "بيانات"
                )) or bool(previous_turn and raw.casefold() in previous_turn[0].text.casefold())
                confidence = 0.86 if grounded else 0.28
                basis = "matching prior context" if grounded else "no matching prior entity"
                resolved = grounded

            out.append(Reference(raw, kind, target, resolved, confidence, basis=basis))

    # Arabic object pronouns are commonly attached directly to verbs. Treat the suffix
    # as a discourse reference only when it is morphologically separated from known
    # prepositional/adverbial forms; resolution uses the same candidate policy as
    # standalone pronouns, so ambiguity remains a clarification rather than a guess.
    for clitic, _start, _end in _attached_arabic_pronouns(text, protected_tokens=protected_tokens):
        prospective_target, prospective_confidence, prospective_basis, prospective_resolved = _prospective_artifact_reference(
            text, _start, clitic
        )
        if prospective_resolved:
            out.append(Reference(clitic, "pronoun", prospective_target, True, prospective_confidence, basis=prospective_basis))
            continue
        candidates = []
        local = _find_candidates(text, _start)
        if local:
            candidates.extend(local)
        if not candidates:
            candidates.extend(previous_turn)
        if not candidates:
            candidates.extend(previous_goal_entities)
        if not candidates and _goal_can_be_reference(last_goal):
            candidates.append(_Candidate(last_goal, "previous-goal"))
        target, confidence, basis, resolved = _pick_unique(candidates, clitic)
        out.append(Reference(clitic, "pronoun", target, resolved, confidence, basis=basis))

    dedup: dict[tuple[str, str], Reference] = {}
    for ref in out:
        key = (ref.text.casefold(), ref.kind)
        if key not in dedup or ref.confidence > dedup[key].confidence:
            dedup[key] = ref
    return list(dedup.values())[:12]

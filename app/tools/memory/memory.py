from app.runtime.registry import tool
from app.knowledge.memory import get_memory
from app.runtime.session_context import current_session_id
from app.intelligence.keywords import NAME_FACT_RE, REMEMBER_RE, RECALL_RE, HISTORY_KW
import re


def _remember_args(goal: str) -> dict:
    arabic_name = re.search(r"(?:أنا\s+)?اسمي\s+(?:هو\s+)?(.+?)\s*[؟?]?$", goal.strip(), re.I | re.S)
    if arabic_name:
        return {"key": "name", "value": arabic_name.group(1).strip()}
    m = NAME_FACT_RE.search(goal)
    if m:
        value = next((v for v in (m.groupdict().get("saved"), m.groupdict().get("stated"), m.groupdict().get("arabic")) if v), "")
        return {"key": "name", "value": value.strip()}
    m = REMEMBER_RE.search(goal)
    if m:
        return {"key": _canonical_memory_key(m.group(1)), "value": m.group(2).strip()}
    generic = re.search(r"(?:افتكر|تذكر(?:\s+أن)?|remember(?:\s+that)?)\s+([^:：=]+)\s*[:：=]\s*(.+)", goal.strip(), re.I | re.S)
    if generic:
        return {"key": _canonical_memory_key(generic.group(1)), "value": generic.group(2).strip()}
    m = re.search(r"\bmy\s+([A-Za-z][\w -]{1,48})\s+(?:is|=)\s+(.+)", goal, re.I | re.S)
    if m:
        return {"key": m.group(1).strip().lower(), "value": m.group(2).strip()}
    raise ValueError("صيغة المعلومة غير مفهومة")


def _recall_args(goal: str) -> dict:
    text = goal.strip()
    preference_key = _recall_key_from_question(text)
    if preference_key:
        return {"key": preference_key}
    if NAME_FACT_RE.search(text) is None and (
        text.casefold().rstrip(" ?؟") in {"what's my name", "what is my name", "do you remember my name", "remember my name", "who am i", "انا مين", "أنا مين"}
        or re.search(r"(?:ما(?:\s+هو)?\s+اسمي|ايه\s+اسمي|إيه\s+اسمي|فاكر\s+اسمي)\s*[?؟]?$", text, re.I)
    ):
        return {"key": "name"}
    m = RECALL_RE.search(text)
    if not m:
        raise ValueError("صيغة الاسترجاع غير مفهومة")
    key = m.groupdict().get("key")
    return {"key": key.strip() if key else "name"}


def _match_remember(goal: str) -> bool:
    g = goal.casefold().strip()
    if re.search(r"(?:what(?:'s| is)\s+my\s+name|do you remember my name|remember my name|who\s+am\s+i|ما(?:\s+هو)?\s+اسمي|ايه\s+اسمي|إيه\s+اسمي|فاكر\s+اسمي)\s*[?؟]?\s*$", g, re.I):
        return False
    return bool(REMEMBER_RE.search(goal) or NAME_FACT_RE.search(goal)
                or re.search(r"(?:^|\b)(?:أنا\s+)?اسمي\s+(?:هو\s+)?[^؟?]+", goal, re.I | re.S)
                or re.search(r"\bmy\s+[A-Za-z][\w -]{1,48}\s+(?:is|=)\s+.+", goal, re.I | re.S))


def _recall_key_from_question(text: str) -> str | None:
    g = text.casefold().strip().rstrip(" ?؟")
    explicit = {
        "what programming language do i prefer": "favorite programming language",
        "what language do i prefer": "favorite programming language",
        "what editor do i prefer": "favorite editor",
        "what color do i prefer": "favorite color",
        "what is my name": "name",
        "what's my name": "name",
        "do you remember my name": "name",
        "who am i": "name",
        "انا مين": "name",
        "أنا مين": "name",
        "where am i from": "origin",
        "where do i come from": "origin",
        "what is my origin": "origin",
        "where do i live": "city",
    }
    if g in explicit:
        return explicit[g]
    m = re.fullmatch(r"what(?:'s| is)\s+my\s+([a-zA-Z][\w -]{0,48})", g, re.I)
    if m:
        return _canonical_memory_key(m.group(1))
    m = re.fullmatch(r"do\s+you\s+remember\s+my\s+([a-zA-Z][\w -]{0,48})", g, re.I)
    if m:
        return _canonical_memory_key(m.group(1))
    m = re.fullmatch(r"what(?:'s| is)\s+([a-zA-Z][\w -]{0,48})", g, re.I)
    if m:
        key = _canonical_memory_key(m.group(1))
        return key if _known_memory_key(key) else None
    m = re.fullmatch(r"فاكر\s+(?:ايه|إيه)\s+عن\s+(.+)", g, re.I)
    if m:
        return _canonical_memory_key(m.group(1))
    m = re.fullmatch(r"ماذا\s+تتذكر\s+عن\s+(.+)", g, re.I)
    if m:
        return _canonical_memory_key(m.group(1))
    m = re.fullmatch(r"what\s+(.+?)\s+do\s+i\s+prefer", g, re.I)
    if m:
        phrase = _canonical_memory_key(m.group(1))
        if phrase in {"programming language", "language"}:
            return "favorite programming language"
        if phrase in {"editor", "color"}:
            return "favorite " + phrase
        return "preferred " + phrase
    return None



def _match_last_result(goal: str) -> bool:
    return bool(re.search(r"^(?:what was (?:the )?(?:last |previous )?(?:result|output)|ما(?: هو)? الناتج|ايه الناتج|إيه الناتج)\s*[?؟]?$", goal.strip(), re.I))


@tool(description="يسترجع ناتج آخر run ناجح في الجلسة/الذاكرة دون إنشاء معلومة جديدة", params={}, stage=0,
      match=_match_last_result, capability="recall_last_result", produces=("last_result_recalled",), cost=0.7, risk="low", parallel_safe=True, intent_priority=10)
def recall_last_result():
    previous = get_memory().last_completed_output(session_id=current_session_id())
    if not previous or previous.get("output") is None:
        return "مفيش ناتج سابق ناجح"
    value = previous["output"]
    if isinstance(value, str):
        m = re.fullmatch(r".*?\s=\s(.+)", value.strip(), re.S)
        if m:
            value = m.group(1).strip()
    return value


def _known_memory_key(key: str) -> bool:
    key = _canonical_memory_key(key)
    if not key:
        return False
    try:
        return get_memory().get_fact(key) is not None
    except Exception:
        return False


def _match_recall(goal: str) -> bool:
    g = goal.casefold().strip()
    if re.search(r"(?:what do you remember about me|what do you know about me|tell me about what you remember about me|ماذا تعرف عني|ماذا تتذكر عني|ذاكرتي|ملفي في الذاكرة)\s*[?؟]?$", g, re.I):
        return False
    key = _recall_key_from_question(goal)
    if RECALL_RE.search(goal):
        return True
    if key:
        # Generic world questions must not become memory lookups, but explicit
        # first-person questions are valid even when the fact is currently absent.
        # The tool will answer honestly that the memory is empty for that key.
        explicit_personal = bool(re.search(r"(?:what(?:'s| is)|do you remember)\s+my\s+", g, re.I))
        preference_question = bool(re.search(r"\bwhat\s+.+?\s+do\s+i\s+prefer\b", g, re.I))
        origin_question = bool(re.search(r"\bwhere\s+(?:am\s+i|do\s+i\s+come)\s+from\b", g, re.I))
        return explicit_personal or preference_question or origin_question or _known_memory_key(key)
    return False


def _canonical_memory_key(raw: str) -> str:
    return get_memory().canonical_key(raw)


def _memory_aliases(key: str) -> list[str]:
    return get_memory().key_aliases(key)


def _forget_args(goal: str) -> dict:
    m = re.search(r"(?:انس|انسى|امسح|forget)\s+(.+)", goal, re.I | re.S)
    return {"key": _canonical_memory_key(m.group(1))}


@tool(description="يحفظ معلومة (افتكر المفتاح: القيمة)", params={"key": "المفتاح", "value": "القيمة"},
      stage=1, requires_approval=True, match=_match_remember, build_args=_remember_args,
      capability="remember_fact", produces=("fact_saved",), cost=1.5, risk="medium", idempotent=True, intent_priority=8)
def remember_fact(key: str, value: str):
    get_memory().set_fact(key, value)
    return f"تم حفظ: {key}"


@tool(description="يسترجع معلومة محفوظة (فاكر ايه عن المفتاح)", params={"key": "المفتاح"}, stage=0,
      match=_match_recall, build_args=_recall_args,
      capability="recall_fact", produces=("fact_recalled",), cost=1.0, risk="low", parallel_safe=True, intent_priority=8)
def recall_fact(key: str):
    v = get_memory().get_fact(key)
    if v is not None:
        return v
    alternates = []
    if key.startswith("favorite "):
        alternates.append("preferred " + key[len("favorite "):])
    elif key.startswith("preferred "):
        alternates.append("favorite " + key[len("preferred "):])
    alternates.extend(_memory_aliases(key))
    for alt in alternates:
        v = get_memory().get_fact(alt)
        if v is not None:
            return v
    hits = get_memory().search_memory(key, top_k=6, kinds={"fact", "preference", "profile", "goal"})
    exact = [h for h in hits if str(h.get("key") or "").casefold() == str(key or "").casefold()]
    if len(exact) == 1:
        return exact[0].get("value")
    return hits if hits else f"مفيش معلومة محفوظة عن {key}"


@tool(description="ينسى معلومة محفوظة", params={"key": "المفتاح"}, stage=1, requires_approval=True,
      match=lambda g: bool(re.search(r"(?:انس|انسى|امسح|forget)\s+", g, re.I)), build_args=_forget_args,
      capability="forget_fact", produces=("fact_deleted",), cost=1.5, risk="medium", idempotent=True)
def forget_fact(key: str):
    canonical = _canonical_memory_key(key)
    if get_memory().delete_fact(canonical):
        return "تم النسيان: " + canonical
    alternatives = []
    if canonical.startswith("favorite "):
        alternatives.append("preferred " + canonical[len("favorite "):])
    elif canonical.startswith("preferred "):
        alternatives.append("favorite " + canonical[len("preferred "):])
    else:
        alternatives.extend(("preferred " + canonical, "favorite " + canonical))
    alternatives.extend(_memory_aliases(canonical))
    for alt in alternatives:
        if get_memory().delete_fact(alt):
            return "تم النسيان: " + alt
    return "لم تكن المعلومة موجودة: " + canonical


@tool(description="آخر الأهداف اللي اتنفذت ونتايجها", stage=0, triggers=HISTORY_KW,
      capability="recent_runs", produces=("run_history_available",), cost=1.0, risk="low", parallel_safe=True)
def recent_runs():
    return [f"{r['goal']} [{r['status']}]" for r in get_memory().recent_runs(5)]

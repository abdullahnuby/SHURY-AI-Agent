import re
from app.runtime.registry import tool
from app.knowledge.memory import get_memory
from app.runtime.session_context import current_session_id
from app.tools.memory.memory import _last_result_for_current_session
from app.knowledge.memory_extraction import extract as extract_candidates
from app.intelligence.understanding import normalize


def _tail(goal: str, prefixes: tuple[str, ...]) -> str:
    text = goal.strip()
    low = text.casefold()
    for prefix in prefixes:
        if low.startswith(prefix.casefold()):
            return text[len(prefix):].strip(" :،,؟?")
    return text


def _search_args(goal: str) -> dict:
    query = _tail(goal, (
        "search memory", "search my memory", "recall from memory", "ابحث في ذاكرتك",
        "ابحث في الذاكرة", "استرجع من الذاكرة", "فتش في ذاكرتك",
    ))
    return {"query": query or goal.strip()}


def _match_search(goal: str) -> bool:
    g=goal.casefold().strip()
    broad=(
        "search memory" in g or "search my memory" in g or "recall from memory" in g
        or "ابحث في ذاكرتك" in g or "ابحث في الذاكرة" in g or "استرجع من الذاكرة" in g
        or "فتش في ذاكرتك" in g
    )
    # Specific single-key questions should continue to use recall_fact.
    return broad and not re.search(r"(?:what(?:'s| is) my name|who am i|ما(?: هو)? اسمي|ما اسمي|فاكر اسمي)\s*[?؟]?$", g, re.I)


@tool(description="يبحث في الذاكرة الموحدة: حقائق وتفضيلات وملاحظات وسجل تفاعلات", params={"query":"سؤال الذاكرة"},
      stage=0, requires_approval=False, match=_match_search, build_args=_search_args,
      capability="memory_search", produces=("memory_recalled",), cost=1.1, risk="low", parallel_safe=True, intent_priority=5)
def search_memory(query: str):
    return get_memory().search_memory(query, top_k=8)


def _remember_memory_args(goal: str) -> dict:
    candidates = extract_candidates(goal)
    if not candidates:
        raise ValueError("لم أجد معلومة آمنة وواضحة للحفظ")
    c = candidates[0]
    args = {"value": c.value, "kind": c.kind}
    if c.key:
        args["key"] = c.key
    return args


def _match_remember_memory(goal: str) -> bool:
    # This tool owns preference-like statements. Explicit facts remain on remember_fact.
    g = normalize(goal)
    return bool(re.search(r"(?:i\s+prefer|i\s+like|i\s+love|i\s+usually\s+use|انا\s+بفضل|انا\s+احب|انا\s+عادة\s+بستخدم)\s+.+", g, re.I | re.S))


@tool(description="يستخرج معلومة أو تفضيل واضح من كلام المستخدم ويحفظه ببيانات provenance", params={"value":"القيمة","kind":"نوع الذاكرة","key":"مفتاح اختياري للذاكرة"},
      stage=1, requires_approval=True, match=_match_remember_memory, build_args=_remember_memory_args,
      capability="remember_memory", produces=("memory_saved",), cost=1.4, risk="medium", idempotent=True, intent_priority=4)
def remember_memory(value: str, kind: str = "fact", key: str = ""):
    mid=get_memory().remember(value, kind=kind or "fact", key=key or None, confidence=0.9, importance=4, source="user", reason="explicit_memory_language")
    return {"id":mid,"kind":kind,"key":key or None,"value":value}



def _remember_result_args(goal: str) -> dict:
    m = re.search(r"(?:save|store)\s+(?:the\s+)?(?:result|output)\s+as\s+([A-Za-z][\w -]{0,48})", goal, re.I)
    if not m:
        m = re.search(r"(?:احفظ|سجل)\s+(?:النتيجة|الناتج)\s+باسم\s+(.+)", goal, re.I | re.S)
    if not m:
        raise ValueError("اسم المعلومة المطلوب حفظ الناتج بها غير واضح")
    return {"key": m.group(1).strip().casefold(), "value": ""}


def _match_remember_result(goal: str) -> bool:
    g = goal.casefold().strip()
    return bool(re.search(r"(?:save|store)\s+(?:the\s+)?(?:result|output)\s+as\s+[a-z][\w -]{0,48}", g, re.I)
                or re.search(r"(?:احفظ|سجل)\s+(?:النتيجة|الناتج)\s+باسم\s+.+", g, re.I | re.S))


@tool(description="يحفظ ناتج الخطوة السابقة كحقيقة معنونة، مع الحفاظ على provenance للـrun", params={"key":"مفتاح المعلومة","value":"الناتج السابق"},
      stage=1, requires_approval=True, match=_match_remember_result, build_args=_remember_result_args, pipe_param="value",
      capability="remember_result", produces=("fact_saved",), cost=1.6, risk="medium", idempotent=True, parallel_safe=False, intent_priority=10)
def remember_result(key: str, value: str):
    # Calculator outputs carry a human-readable pipe label (e.g. `25*16 = 400`).
    # For a fact, persist the actual result rather than the presentation wrapper.
    stored_value = value
    if isinstance(value, str):
        m = re.fullmatch(r".*?\s=\s(.+)", value.strip(), re.S)
        if m:
            stored_value = m.group(1).strip()
    mid = get_memory().remember(stored_value, kind="fact", key=key, confidence=1.0, importance=5, source="user",
                                 reason="explicit_result_save")
    return {"id": mid, "key": key, "value": stored_value}


def _remember_last_result_args(goal: str) -> dict:
    m = re.search(r"(?:save|store|remember)\s+(?:the\s+)?(?:previous\s+result|last\s+result|previous\s+output|last\s+output)\s+as\s+([A-Za-z][\w -]{0,48})", goal, re.I)
    if not m:
        m = re.search(r"(?:احفظ|سجل)\s+(?:النتيجة|الناتج)\s+(?:السابقة|السابق|اللي فات)\s+باسم\s+(.+)", goal, re.I | re.S)
    if not m:
        raise ValueError("اسم المعلومة المطلوب حفظ الناتج السابق بها غير واضح")
    return {"key": m.group(1).strip().casefold()}


def _match_remember_last_result(goal: str) -> bool:
    g = goal.casefold().strip()
    return bool(re.search(r"(?:save|store|remember)\s+(?:the\s+)?(?:previous\s+result|last\s+result|previous\s+output|last\s+output)\s+as\s+[a-z][\w -]{0,48}", g, re.I)
                or re.search(r"(?:احفظ|سجل)\s+(?:النتيجة|الناتج)\s+(?:السابقة|السابق|اللي فات)\s+باسم\s+.+", g, re.I | re.S))


@tool(description="يحفظ ناتج آخر run ناجح كحقيقة معنونة؛ يستخدم فقط في طلبات متعددة الأدوار ذات إشارة صريحة للناتج السابق", params={"key":"مفتاح المعلومة"},
      stage=1, requires_approval=True, match=_match_remember_last_result, build_args=_remember_last_result_args,
      capability="remember_last_result", produces=("fact_saved",), cost=1.7, risk="medium", idempotent=True, parallel_safe=False, intent_priority=11)
def remember_last_result(key: str):
    previous = _last_result_for_current_session()
    if not previous or previous.get("output") is None:
        raise ValueError("لا يوجد ناتج سابق ناجح يمكن حفظه")
    value = previous["output"]
    if isinstance(value, str):
        m = re.fullmatch(r".*?\s=\s(.+)", value.strip(), re.S)
        if m:
            value = m.group(1).strip()
    mid = get_memory().remember(str(value), kind="fact", key=key, confidence=1.0, importance=5, source="user",
                                 reason="explicit_previous_result_save")
    return {"id": mid, "key": key, "value": str(value), "source_run_id": previous.get("run_id")}

def _match_profile(goal: str) -> bool:
    g=goal.casefold().strip().rstrip("?؟")
    return g in {"memory profile", "my memory", "what do you know about me", "what do you remember about me", "ذاكرتي", "ملفي في الذاكرة", "ماذا تعرف عني", "ماذا تتذكر عني"}


@tool(description="يعرض ملخص ذاكرة المستخدم الحالية بدون إظهار التاريخ المحذوف", stage=0,
      triggers=("memory profile","my memory","what do you know about me","what do you remember about me","ذاكرتي","ملفي في الذاكرة","ماذا تعرف عني","ماذا تتذكر عني"),
      match=_match_profile,
      capability="memory_profile", produces=("memory_profile_available",), cost=0.8, risk="low", parallel_safe=True, intent_priority=6)
def memory_profile():
    return get_memory().profile(limit=50)


@tool(description="يعرض إحصائيات الذاكرة الحالية", params={}, name="memory_stats", stage=0,
      match=lambda g: bool(re.search(r"(?:^|\b)(?:memory stats|memory statistics|إحصائيات الذاكرة|احصائيات الذاكرة)(?:\b|$)", normalize(g), re.I)),
      capability="memory_stats", produces=("memory_stats_available",), cost=0.6, risk="low", parallel_safe=True, idempotent=True, intent_priority=7)
def memory_stats():
    return get_memory().memory_stats()


@tool(description="يعرض سجل تغييرات ذاكرة معينة", params={"key":"مفتاح المعلومة"}, stage=0,
      match=lambda g: bool(re.search(r"(?:memory history|history of memory|تاريخ المعلومة|تاريخ الذاكرة)\s+.+", g, re.I)),
      build_args=lambda g:{"key":_tail(g,("memory history ","history of memory ","تاريخ المعلومة ","تاريخ الذاكرة "))},
      capability="memory_history", produces=("memory_history_available",), cost=1.0, risk="low", parallel_safe=True)
def memory_history(key: str):
    return get_memory().memory_history(key=key, limit=50)


@tool(description="يعرض العلاقات المحفوظة حول كيان", params={"subject":"اسم الكيان"}, stage=0,
      match=lambda g: bool(re.search(r"(?:memory graph|graph memory|علاقات الذاكرة|جراف الذاكرة)\s+.+", g, re.I)),
      build_args=lambda g:{"subject":_tail(g,("memory graph ","graph memory ","علاقات الذاكرة ","جراف الذاكرة "))},
      capability="memory_graph", produces=("memory_graph_available",), cost=1.0, risk="low", parallel_safe=True)
def memory_graph(subject: str):
    return get_memory().graph(subject)


@tool(description="يدمج الذاكرة المتكررة ويغلق العناصر منتهية الصلاحية دون حذف المصدر", stage=1, requires_approval=True,
      triggers=("consolidate memory","memory consolidate","ادمج الذاكرة","وحد الذاكرة"),
      capability="memory_consolidate", produces=("memory_consolidated",), cost=1.8, risk="medium", idempotent=True, intent_priority=4)
def memory_consolidate():
    return get_memory().consolidate()


@tool(description="ينظف الذاكرة المنتهية أو القديمة منخفضة الأهمية مع إبقاء التاريخ", stage=1, requires_approval=True,
      triggers=("cleanup memory","memory cleanup","نظف الذاكرة","نظف الذاكره"),
      capability="memory_cleanup", produces=("memory_cleaned",), cost=1.5, risk="medium", idempotent=True, intent_priority=4)
def memory_cleanup():
    return get_memory().cleanup()


@tool(description="يمسح كل الذاكرة الشخصية النشطة مع حذف سجل المحادثات المحلي للنطاق المحدد", stage=1, requires_approval=True,
      triggers=("forget everything about me","delete all my memories","erase all memory","امسح كل ذاكرتي","انس كل حاجة عني","انس كل ما تعرفه عني"),
      match=lambda g: any(x in g.casefold() for x in ("forget everything about me","delete all my memories","erase all memory","امسح كل ذاكرتي","انس كل حاجة عني","انس كل ما تعرفه عني")),
      capability="memory_forget_all", produces=("memory_forgotten_all",), cost=2.5, risk="high", idempotent=True, intent_priority=9)
def memory_forget_all():
    return get_memory().forget_all(include_episodes=True)


@tool(description="يعرض صحة الذاكرة: الأنواع النشطة، العناصر التي ستنتهي قريبًا، وسلامة القيود الزمنية", stage=0,
      triggers=("memory health", "health of memory", "صحة الذاكرة", "سلامة الذاكرة"),
      capability="memory_health", produces=("memory_health_available",), cost=0.5, risk="low", parallel_safe=True)
def memory_health():
    return get_memory().memory_health()

"""Deterministic language understanding with bilingual intent aliases and evidence scoring.

The runtime stays deterministic after semantic extraction, but it must not confuse literal trigger
coverage with understanding.  This module provides a small normalized intent layer
that tools can use as a semantic fallback when an exact trigger does not match.
"""
from dataclasses import dataclass, field
import re
import unicodedata

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
ALEF = str.maketrans("إأآٱ", "اااا")
_ARABIC_DIACRITICS = r"[ًٌٍَُِّْـ]"


def normalize(text: str) -> str:
    text = str(text or "").translate(ARABIC_DIGITS).translate(ALEF)
    text = re.sub(_ARABIC_DIACRITICS, "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return unicodedata.normalize("NFKC", text)


@dataclass(frozen=True)
class Intent:
    name: str
    score: float
    evidence: tuple[str, ...] = ()


@dataclass
class Understanding:
    original: str
    normalized: str
    intents: list[Intent] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    ambiguous: bool = False

    @property
    def top_intent(self) -> Intent | None:
        return self.intents[0] if self.intents else None

    def score_for(self, *names: str) -> float:
        wanted = {str(x) for x in names}
        return max((i.score for i in self.intents if i.name in wanted), default=0.0)


# We intentionally use phrase/alias evidence rather than a single literal trigger.
# This improves routing without introducing an opaque model dependency.
INTENT_RULES: dict[str, tuple[tuple[str, float], ...]] = {
    "greeting": (("hello", 5), ("hi", 5), ("hey", 5), ("good morning", 5), ("good afternoon", 5),
                  ("good evening", 5), ("good day", 5), ("اهلا", 5), ("أهلا", 5), ("اهلا وسهلا", 5),
                  ("أهلا وسهلا", 5), ("اهلا بيك", 5), ("أهلا بيك", 5), ("السلام عليكم", 5), ("ازيك", 5),
                  ("إزيك", 5), ("عامل ايه", 5), ("عامل إيه", 5)),
    "calculate": (("احسب", 3), ("حساب", 2), ("calc", 3), ("calculate", 3), ("calculator", 2),
                  ("ضرب", 2), ("زائد", 2), ("ناقص", 2), ("مقسوم", 2), ("multiply", 2), ("divide", 2)),
    "save_note": (("سجل", 3), ("احفظ", 3), ("فكرني", 3), ("فكرنى", 3), ("فكرني ان", 2), ("ذكرني", 3),
                   ("ذكرنى", 3), ("remind me", 4), ("reminder", 3), ("remember that", 3), ("save note", 3), ("save", 2), ("note", 2)),
    "time": (("الساعة", 2), ("الوقت", 2), ("التاريخ", 2), ("time", 2), ("date", 2), ("what time", 3)),
    "list_notes": (("اعرض الملاحظات", 4), ("ملاحظاتي", 3), ("list notes", 3), ("show notes", 3)),
    "search_notes": (("دور على", 3), ("ابحث عن", 3), ("ابحث في الملاحظات", 5), ("دور في الملاحظات", 5), ("search notes", 4), ("search my notes", 4), ("find note", 3), ("find notes", 3)),
    "remember_fact": (("افتكر", 4), ("تذكر أن", 3), ("remember that", 3), ("remember", 2),
                       ("save my name", 5), ("save me name", 5), ("store my name", 5), ("my name is", 5),
                       ("احفظ اسمي", 5), ("سجل اسمي", 5), ("اسمي", 5), ("اسمي هو", 5)),
    "recall_last_result": (("what was the result", 5), ("what was the last result", 6), ("what was the previous result", 6),
                           ("what was the output", 5), ("ما هو الناتج", 6), ("ما الناتج", 5), ("ايه الناتج", 5), ("إيه الناتج", 5)),
    "recall_fact": (("فاكر", 4), ("do you remember my name", 6), ("remember my name", 5), ("recall", 4), ("what do you remember", 3), ("what's my name", 5),
                    ("what is my name", 5), ("who am i", 5), ("ما اسمي", 5), ("ما هو اسمي", 5),
                    ("ايه اسمي", 5), ("إيه اسمي", 5), ("فاكر اسمي", 5),
                    ("what programming language do i prefer", 5), ("what language do i prefer", 4),
                    ("what editor do i prefer", 4), ("what color do i prefer", 4)),
    "memory_search": (("search my memory", 6), ("search memory", 6), ("ابحث في ذاكرتك", 6), ("ابحث في الذاكرة", 6), ("استرجع من الذاكرة", 6), ("فتش في ذاكرتك", 6)),
    "memory_profile": (("what do you know about me", 7), ("what do you remember about me", 7), ("tell me about what you remember about me", 7), ("my memory", 5), ("memory profile", 5), ("ماذا تعرف عني", 7), ("ماذا تتذكر عني", 7), ("ذاكرتي", 5), ("ملفي في الذاكرة", 5)),
    "remember_result": (("save the result as", 6), ("store the result as", 6), ("احفظ النتيجة باسم", 6), ("سجل النتيجة باسم", 6)),
    "remember_last_result": (("save the previous result as", 6), ("save the last result as", 6), ("store the previous result as", 6), ("احفظ النتيجة السابقة باسم", 6), ("احفظ الناتج السابق باسم", 6)),
    "remember_memory": (("i prefer", 5), ("i like", 4), ("i usually use", 4), ("انا بفضل", 5), ("انا احب", 4), ("انا عادة بستخدم", 4)),
    "forget_fact": (("انس", 4), ("انسى", 4), ("امسح المعلومة", 3), ("forget", 4), ("delete memory", 4)),
    "history": (("اخر الاهداف", 4), ("آخر الأهداف", 4), ("السجل", 2), ("history", 4), ("recent runs", 4)),

    "open_world_learning": (("research and learn", 7), ("learn from the internet", 7), ("learn from internet", 7),
                             ("learn online", 6), ("deep research and learn", 7), ("ابحث وتعلم", 7),
                             ("تعلم من الانترنت", 7), ("تعلم من الإنترنت", 7), ("تعلم من الويب", 7),
                             ("تعلم من البحث", 6), ("بحث وتعلم", 6)),
    "scientific_research": (("latest research", 4), ("newest research", 4), ("latest papers", 5), ("newest papers", 5), ("latest scientific papers", 5),
                             ("scientific paper", 4), ("research paper", 4), ("arxiv", 4), ("أحدث الأبحاث", 5),
                             ("أحدث أبحاث", 5), ("أحدث الأوراق العلمية", 5), ("الأوراق العلمية", 4), ("أبحاث علمية", 4),
                             ("ورقة علمية", 4), ("ابحث في arxiv", 5)),
    "web_research": (("search online", 4), ("search the internet", 5), ("research the web", 5), ("web research", 5),
                      ("browse the web", 4), ("ابحث على الانترنت", 5), ("ابحث على الإنترنت", 5),
                      ("ابحث على الويب", 5), ("دور على الانترنت", 4)),
    "github_discovery": (("github search", 5), ("search github repositories", 5), ("find github repos", 5),
                          ("ابحث عن مشاريع github", 5), ("دور على مشاريع github", 5)),
    "github_learning": (("github research", 5), ("inspect github", 5), ("analyze github repo", 5),
                         ("ابحث في github", 4), ("حلل مستودع github", 5), ("تعلم من github", 5)),

    "data_analysis": (("analyze dataset", 5), ("analyze the dataset", 5), ("analyze data", 5), ("dataset analysis", 5),
                       ("profile dataset", 5), ("dataset profile", 5), ("data profile", 5), ("profile the dataset", 5), ("data analysis", 4), ("حلل البيانات", 5),
                       ("حلل ملف", 4), ("تحليل البيانات", 5), ("تحليل شامل", 5), ("تشخيص البيانات", 5),
                       ("outlier", 4), ("anomalies", 4), ("شذوذ", 4), ("القيم الشاذة", 4), ("متوسط", 2),
                       ("correlation", 3), ("ارتباط", 3)),
    "workspace_reasoning": (("analyze workspace", 5), ("workspace analysis", 5), ("multiple files", 4),
                             ("join files", 5), ("heterogeneous workspace", 5), ("اربط البيانات", 5),
                             ("عدة ملفات", 4), ("مساحة البيانات", 5), ("حلل المجلد", 5)),

    "development_validation": (("build project", 5), ("build the project", 5), ("run project tests", 5),
                                ("run the tests", 5), ("test project", 5), ("check project", 5),
                                ("compile the project", 4), ("build and test", 6), ("ابني المشروع", 5),
                                ("ابني المشروع واختبر", 6), ("اختبر المشروع", 5), ("شغل الاختبارات", 5),
                                ("افحص build", 4), ("افحص المشروع", 3)),
    "development_inspection": (("inspect project", 5), ("inspect the project", 5), ("analyze project", 5),
                                ("inspect repository", 5), ("analyze the repo", 4), ("حلل المشروع", 5),
                                ("افحص المشروع", 5), ("حلل الريبو", 5)),
    "development_learning": (("learn project", 5), ("learn development", 5), ("learn to build", 4),
                              ("learn to manage", 4), ("تعلم تطوير", 5), ("تعلم من المشروع", 5),
                              ("تعلم بناء المشروع", 5), ("تعلم ادارة المشروع", 5)),
    "development_git": (("git status", 5), ("repository status", 5), ("git state", 4), ("حالة git", 5), ("حالة المستودع", 5)),

    "skill_discovery": (("discover skills", 6), ("find skills", 6), ("search skills", 6), ("find a skill", 5),
                         ("اكتشف المهارات", 6), ("اكتشف مهارات", 6), ("ابحث عن مهارات", 6), ("دور على skills", 5)),
    "skill_routing": (("route skills", 6), ("skill router", 6), ("find the right skill", 6), ("route skill", 5),
                       ("وجه المهارات", 6), ("روتر المهارات", 6), ("ما المهارة المناسبة", 5)),
    "skill_acquisition": (("install skill", 6), ("install remote skill", 6), ("install a skill", 6), ("import skill", 5),
                           ("download skill", 5), ("ثبت مهارة", 6), ("نزّل skill", 6), ("ثبت skill من github", 6),
                           ("استورد المهارة", 5)),
    "skill_trust": (("approve skill", 6), ("trust skill", 6), ("activate trusted skill", 6), ("اعتمد المهارة", 6), ("ثق في المهارة", 6)),
    "skill_lifecycle": (("activate skill", 5), ("retire skill", 5), ("promote skill", 5), ("demote skill", 5),
                         ("رقّي المهارة", 5), ("خفض المهارة", 5), ("أوقف المهارة", 5), ("فعّل المهارة", 5)),

    "agentic_rag": (("agentic rag", 6), ("agentic retrieval", 6), ("evidence loop", 5), ("بحث وكيل", 6), ("ابحث بشكل تكراري", 6), ("تحقق من الأدلة", 5)),
    "rag_reasoning": (("rag", 5), ("retrieval augmented", 5), ("retrieve evidence", 5), ("ask the knowledge base", 5),
                       ("استرجع الأدلة", 5), ("ابحث في المعرفة", 5), ("اسأل المعرفة", 5)),
    "rag_indexing": (("index knowledge", 5), ("index corpus", 5), ("rag index", 5), ("index memory", 4),
                      ("فهرس المعرفة", 5), ("فهرس الذاكرة", 5), ("افهرس الذاكرة", 5)),
    "agent_observability": (("runtime analytics", 5), ("analyze runtime", 5), ("analytics", 4), ("حلل أداء", 5), ("تحليل الاداء", 5), ("حلل السجل", 5)),
}


def _entity(pattern: str, text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(pattern, text, re.I | re.S)]


def _score_phrase(term: str, weight: float, text: str) -> tuple[float, str | None]:
    # Normalize aliases too, so Arabic alef variants/diacritics do not create hidden
    # misses between the intent vocabulary and the normalized user text.
    term_n = normalize(term)
    # Word boundaries for ASCII aliases prevent 'date' matching 'candidate'.
    if re.search(r"[A-Za-z]", term_n):
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(term_n) + r"(?![A-Za-z0-9_])"
    else:
        pattern = re.escape(term_n)
    if re.search(pattern, text, re.I):
        return weight, term
    return 0.0, None


def understand(text: str) -> Understanding:
    n = normalize(text)
    intents: list[Intent] = []
    for name, terms in INTENT_RULES.items():
        score = 0.0
        evidence: list[str] = []
        for term, weight in terms:
            hit, why = _score_phrase(term, weight, n)
            score += hit
            if why:
                evidence.append(why)
        if name == "calculate" and re.search(r"(?<!\w)\d+(?:\s*[+\-*/%^x×÷]\s*\d+)+", n):
            score += 4
            evidence.append("numeric-expression")
        if score:
            intents.append(Intent(name, score, tuple(evidence)))
    # Resolve high-signal context clashes before normalization. A generic token such as
    # "rag" must not beat an explicit web/learning request, and explicit fact syntax
    # must beat the broader note intent. This is deterministic contextual disambiguation,
    # not a fuzzy semantic fallback.
    adjusted = {i.name: i for i in intents}
    if re.search(r"(?:remember(?: that)?|تذكر أن|افتكر)\s+.+?\s*[:=]\s*.+", n, re.I | re.S):
        for name, delta in (("remember_fact", 5.0), ("save_note", -2.0)):
            if name in adjusted:
                i = adjusted[name]
                adjusted[name] = Intent(i.name, max(0.0, i.score + delta), i.evidence + ("explicit-fact-syntax",))
    # Name-specific commands are higher-confidence than the generic save/remember
    # note language. Keep this deterministic so execution remains reproducible.
    preference_recall_context = bool(re.search(
        r"(?:what\s+(?:programming\s+)?language\s+do\s+i\s+prefer|what\s+editor\s+do\s+i\s+prefer|what\s+color\s+do\s+i\s+prefer)",
        n, re.I,
    ))
    if preference_recall_context and "recall_fact" in adjusted:
        i = adjusted["recall_fact"]
        adjusted["recall_fact"] = Intent(i.name, i.score + 7.0, i.evidence + ("preference-recall-context",))

    name_recall_context = bool(re.search(
        r"(?:what(?:'s| is)\s+my\s+name|do you remember my name|remember my name|who\s+am\s+i|ما(?:\s+هو)?\s+اسمي|ايه\s+اسمي|إيه\s+اسمي|فاكر\s+اسمي)\s*[?؟]?$",
        n, re.I,
    ))
    name_save_context = bool(re.search(
        r"(?:save|store|remember)(?:\s+that)?\s+(?:me\s+)?(?:my\s+)?name\s*(?:as|is)?:?\s+.+"
        r"|(?:my\s+name|اسمي)\s*(?:is|هو|=|:)\s+.+"
        r"|(?:احفظ|سجل|افتكر)\s+(?:اسمي|الاسم)\s*(?:هو|=|:)\s+.+",
        n, re.I | re.S,
    ))
    if name_save_context and "remember_fact" in adjusted:
        i = adjusted["remember_fact"]
        adjusted["remember_fact"] = Intent(i.name, i.score + 6.0, i.evidence + ("name-fact-context",))
        if "save_note" in adjusted:
            i = adjusted["save_note"]
            adjusted["save_note"] = Intent(i.name, max(0.0, i.score - 5.0), i.evidence)
    if "memory_profile" in adjusted and re.search(r"(?:what do you know about me|ماذا تعرف عني|my memory|ذاكرتي|ملفي في الذاكرة)$", n, re.I):
        i=adjusted["memory_profile"]
        adjusted["memory_profile"]=Intent(i.name,i.score+5.0,i.evidence+("profile-context",))
    if "memory_search" in adjusted and re.search(r"(?:search my memory|search memory|ابحث في ذاكرتك|ابحث في الذاكرة|استرجع من الذاكرة|فتش في ذاكرتك)", n, re.I):
        i=adjusted["memory_search"]
        adjusted["memory_search"]=Intent(i.name,i.score+4.0,i.evidence+("memory-search-context",))
    if "remember_memory" in adjusted and not re.search(r"(?:remember that|تذكر أن|افتكر)", n, re.I):
        i=adjusted["remember_memory"]
        adjusted["remember_memory"]=Intent(i.name,i.score+3.0,i.evidence+("preference-context",))

    if name_recall_context and "recall_fact" in adjusted:
        i = adjusted["recall_fact"]
        adjusted["recall_fact"] = Intent(i.name, i.score + 6.0, i.evidence + ("name-recall-context",))

    web_context = any(x in n for x in ("search the internet", "search online", "research the web", "web research", "browse the web", "ابحث على الانترنت", "ابحث على الإنترنت", "ابحث على الويب"))
    learning_context = any(x in n for x in ("learn from the internet", "learn from internet", "learn online", "research and learn", "تعلم من الانترنت", "تعلم من الإنترنت", "تعلم من الويب", "ابحث وتعلم"))
    scientific_context = any(x in n for x in ("latest research", "newest research", "latest papers", "newest papers", "scientific paper", "research paper", "arxiv", "أحدث الأبحاث", "أحدث أبحاث", "أحدث الأوراق العلمية", "ورقة علمية", "أبحاث علمية"))
    if web_context and "web_research" in adjusted:
        i = adjusted["web_research"]
        adjusted["web_research"] = Intent(i.name, i.score + 5.0, i.evidence + ("explicit-web-context",))
        if "rag_reasoning" in adjusted:
            i = adjusted["rag_reasoning"]
            adjusted["rag_reasoning"] = Intent(i.name, max(0.0, i.score - 4.0), i.evidence)
    elif learning_context and "open_world_learning" in adjusted:
        i = adjusted["open_world_learning"]
        adjusted["open_world_learning"] = Intent(i.name, i.score + 5.0, i.evidence + ("explicit-learning-context",))
        if "rag_reasoning" in adjusted:
            i = adjusted["rag_reasoning"]
            adjusted["rag_reasoning"] = Intent(i.name, max(0.0, i.score - 4.0), i.evidence)
    elif scientific_context and "scientific_research" in adjusted:
        i = adjusted["scientific_research"]
        adjusted["scientific_research"] = Intent(i.name, i.score + 4.0, i.evidence + ("explicit-scientific-context",))
    intents = [i for i in adjusted.values() if i.score > 0]
    intents.sort(key=lambda x: (-x.score, x.name))
    total = sum(i.score for i in intents) or 1.0
    if intents:
        intents = [Intent(i.name, round(i.score / total, 3), i.evidence) for i in intents]
    ambiguous = len(intents) > 1 and (intents[0].score - intents[1].score) < 0.12
    entities = {
        "expression": _entity(r"(?:احسب|حساب|calc|calculate)\s+(.+?)(?:\s+(?:واحفظ|ثم احفظ)|$)", n),
        "note": _entity(r"(?:سجل لي|سجل عندي|سجل|احفظ|فكرني|ذكرني|remind me|remember that|save|note)\s+(.+)", text),
        "search": _entity(r"(?:دور على|ابحث عن|search)\s+(.+)", text),
        "fact": _entity(r"(?:افتكر|remember that)\s+(.+?)\s*[:=]\s*(.+)", text),
        "recall_key": _entity(r"(?:فاكر\s+(?:ايه|إيه)\s+عن|recall)\s+(.+)", text),
        "repo": re.findall(r"\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b", text),
        "path": re.findall(r"(?:[A-Za-z]:[\\/]|/)[^\s,;]+", text),
    }
    entities["number"] = re.findall(r"(?<!\w)\d+(?:\.\d+)?", n)
    return Understanding(text, n, intents, {k: v for k, v in entities.items() if v}, ambiguous)

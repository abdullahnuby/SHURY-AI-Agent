from __future__ import annotations

import os
import math
import re
from app.intelligence.understanding import understand, normalize
from .models import IntentCandidate
from .retrieval import rank_query_against_texts

# Layer-2 routing combines auditable lexical rules with Arabic semantic retrieval.
# The retrieval model is a Sentence Transformer used for similarity, never for
# generation, execution decisions, or free-form answers.
ROUTES: dict[str, tuple[tuple[str, ...], str]] = {
    "greeting": (("hello", "hi", "hey", "good morning", "good afternoon", "good evening",
                  "good day", "hi there", "hello there", "hey there", "اهلا", "أهلا", "اهلا وسهلا", "أهلا وسهلا", "السلام عليكم",
                  "ازيك", "إزيك", "عامل ايه", "عامل إيه"), "social"),
    "how_are_you": (("how are you", "how are you doing", "how is it going", "how's it going", "what's up",
                      "how are things", "عامل ايه اخبارك", "عامل إيه أخبارك"), "social"),
    "thanks": (("thanks", "thank you", "thanks a lot", "thank you so much", "much appreciated",
                 "شكرا", "شكرًا", "متشكر", "متشكرة", "تسلم"), "social"),
    "goodbye": (("goodbye", "bye", "see you", "see you later", "take care", "مع السلامة", "سلام"), "social"),
    "acknowledgement": (("ok", "okay", "got it", "understood", "sure", "تمام", "ماشي", "حاضر"), "social"),
    "calculate": ((
        "calculate an expression", "compute a number", "do a calculation", "work out the arithmetic",
        "multiply numbers", "divide numbers", "add numbers", "subtract numbers", "how much is 25 divided by 5",
        "what is 12 times 7", "subtract 9 from 20", "divide 81 by 9", "multiply 5 by 6", "add 3 and 4",
        "احسب عملية حسابية", "احسب ضرب قسمة جمع طرح", "اضرب", "اقسم", "اطرح", "اجمع"
    ), "system"),
    "time": ((
        "what time is it", "tell me the current time", "what is the date", "current time right now",
        "what day is today", "الساعة كام", "الوقت كام", "ما هو الوقت الحالي"
    ), "system"),
    "query_capabilities": ((
        "what can you do", "what are your capabilities", "what can you help with", "what do you support",
        "what are you able to do", "ماذا تستطيع", "ما الذي تستطيع", "انت بتعمل ايه", "إنت بتعمل إيه",
        "بتعرف تعمل ايه", "بتعرف تعمل إيه"
    ), "system"),
    "remember_fact": ((
        "remember that my name is", "store my city", "remember this fact", "save this information",
        "keep this fact", "my name is", "i'm from", "i am from", "i'm originally from", "i am originally from", "i come from", "i was born in", "اسمي", "مدينتي هي", "انا من", "أنا من", "انا اصلي من", "أنا أصلي من", "احفظ هذه المعلومة"
    ), "memory"),
    "recall_fact": ((
        "what is my name", "who am i", "what is my city", "where is my city", "what city am i in", "what city do i live in", "what language do i prefer", "what is my preferred editor",
        "do you remember my name", "tell me my name", "tell me my name again", "say my name again", "where am i from", "where do i come from", "what is my origin", "ما اسمي", "قولي اسمي", "قولّي اسمي", "قولي اسمي تاني", "قولّي اسمي تاني", "ما هي مدينتي", "من انا", "انا من فين", "ايه اسمي", "إيه اسمي", "إيه مدينتي"
    ), "memory"),
    "memory_search": ((
        "search my memory", "search the memory", "look through my memories", "find this in memory",
        "search past conversations", "ابحث في ذاكرتي", "ابحث في ذاكرتك", "فتش في الذاكرة"
    ), "memory"),
    "memory_profile": ((
        "what do you remember about me", "what do you know about me", "show my memory profile",
        "tell me what you remember about me", "personal memory profile", "ماذا تعرف عني", "ماذا تتذكر عني"
    ), "memory"),
    "memory_stats": ((
        "memory stats", "memory statistics", "memory health statistics", "إحصائيات الذاكرة", "احصائيات الذاكرة"
    ), "memory"),
    "forget_fact": ((
        "forget my city", "forget my origin", "forget where i am from", "forget this fact", "remove that memory", "delete that memory", "erase this remembered fact",
        "forget the saved fact", "انس هذه المعلومة", "امسح هذه المعلومة", "احذف الذاكرة"
    ), "memory"),
    "remember_result": ((
        "save the result as a named fact", "store the output as a named fact", "save the result under a name",
        "احفظ النتيجة باسم", "سجل الناتج باسم"
    ), "memory"),
    "remember_last_result": ((
        "save the previous result as a named fact", "save the last result under a name", "store the previous output as a fact", "remember the last result as a named fact", "remember the previous result as a named fact",
        "احفظ النتيجة السابقة باسم", "احفظ الناتج السابق باسم"
    ), "memory"),
    "web_research": ((
        "search the web", "search online", "look online", "browse the internet", "find current information online",
        "search today's news online", "ابحث على الانترنت", "دور اونلاين", "ابحث على الويب"
    ), "research"),
    "scientific_research": ((
        "find recent academic papers", "search the scientific literature", "find research papers", "look for academic studies",
        "latest scientific research", "newest research papers", "find papers on arxiv", "أحدث الأبحاث العلمية", "الأوراق العلمية"
    ), "research"),
    "open_world_learning": ((
        "learn from the internet", "research and learn about", "learn how to improve", "study this topic online",
        "teach yourself from online sources", "ابحث وتعلم", "تعلم من الإنترنت", "تعلم من الانترنت"
    ), "research"),
    "github_discovery": ((
        "find github repositories", "search github repositories", "find github projects", "discover repos on github",
        "search github for projects", "ابحث عن مشاريع github", "دور على مستودعات github"
    ), "skills"),
    "github_learning": ((
        "research this github project", "analyze this github repository", "study the architecture of this github repo",
        "learn from this github project", "inspect a github repository deeply", "حلل مستودع github", "تعلم من github"
    ), "skills"),
    "skill_selection": ((
        "match skills", "match skills for", "select skills", "which skills fit", "find a skill for data analysis",
        "ما المهارات المناسبة", "طابق المهارات"
    ), "skills"),
    "skill_discovery": ((
        "find skills for this task", "discover agent skills", "search for useful skills", "find capabilities for this job",
        "ابحث عن مهارات", "اكتشف مهارات"
    ), "skills"),
    "data_analysis": ((
        "analyze this dataset", "profile the data", "profile data", "find anomalies in the data", "find outliers in the dataset",
        "analyze statistics and correlations", "what is the average value", "what is the mean", "find the average",
        "diagnose the dataset", "حلل البيانات", "حلل ملف البيانات", "متوسط البيانات"
    ), "analysis"),
    "workspace_reasoning": ((
        "analyze the workspace", "inspect all files in the workspace", "join these files", "compare multiple data files",
        "analyze a folder of files", "حلل المجلد", "اربط البيانات بين الملفات"
    ), "analysis"),
    "development_validation": ((
        "run the tests and build the project", "verify the repository still compiles", "validate the project",
        "check whether the codebase passes its tests", "run the project's checks",
        "check whether this project is ready for release", "is this project ready for release",
        "check release readiness", "release readiness audit", "production readiness check",
        "check whether the project is ready for production",
        "اختبر المشروع وابنيه", "تحقق من ان المشروع يبني", "هل المشروع جاهز للاطلاق",
        "هل المشروع جاهز للإطلاق", "فحص جاهزية الاطلاق", "فحص جاهزية الإنتاج"
    ), "development"),
    "development_inspection": ((
        "inspect this repository", "understand the project architecture", "what stack does this project use",
        "inspect the codebase structure", "analyze the repository architecture",
        "code review", "review the code", "review the codebase", "review repository code", "review it", "review this", "check it", "check this", "inspect it", "inspect this",
        "مراجعة الكود", "راجع الكود", "راجعها", "راجعه", "افحصه", "افحصها", "افحص هيكل المشروع"
    ), "development"),
    "development_git": ((
        "show git status", "check the git branch", "show recent git changes", "inspect uncommitted changes",
        "what is the current git status", "اعرض حالة git", "اعرض التغييرات الأخيرة"
    ), "development"),
    "rag_reasoning": ((
        "retrieve evidence from the knowledge base", "answer using indexed documents", "use the indexed documents",
        "search the indexed knowledge", "retrieve supporting evidence", "use the knowledge base to answer",
        "rag provenance", "rag temporal memory", "استرجع الأدلة من قاعدة المعرفة"
    ), "research"),
    "agentic_rag": ((
        "agentic rag", "agentic retrieval", "iteratively search and verify evidence",
        "research with evidence verification", "search, verify and cite", "ابحث بشكل تكراري",
        "بحث وكيل مع التحقق", "ابحث وتحقق من الأدلة"
    ), "research"),
}

STOP = {
    "the", "a", "an", "is", "my", "me", "to", "for", "and", "or", "of", "in", "on", "with", "from",
    "what", "how", "can", "you", "do", "i", "it", "this", "that", "please", "tell", "about", "does",
}


def _tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{1,}|[\u0600-\u06ff]{2,}", normalize(text)) if x not in STOP}


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    s = f"  {normalize(text)}  "
    return {s[i:i+n] for i in range(max(0, len(s)-n+1))}


def _similarity(query: str, example: str) -> float:
    q = normalize(query)
    e = normalize(example)
    if e and e in q:
        return 0.98
    a, b = _tokens(q), _tokens(e)
    lexical = (len(a & b) / max(1, len(a | b))) if a and b else 0.0
    ca, cb = _char_ngrams(q), _char_ngrams(e)
    char = len(ca & cb) / max(1, len(ca | cb))
    return 0.65 * lexical + 0.35 * char


def _route_score(query: str, examples: tuple[str, ...]) -> float:
    return max((_similarity(query, example) for example in examples), default=0.0)


def _context_boost(text: str, name: str) -> float:
    n = normalize(text)
    boost = 0.0
    if re.search(r"\b(?:academic|scientific|research|paper|papers|literature|arxiv)\b|أبحاث|علمي|الأوراق العلمية", n, re.I):
        if name == "scientific_research": boost += 0.36
        if name == "rag_reasoning": boost -= 0.18
    if re.search(r"\b(?:search|find)\s+github\s+repositories?\b", n, re.I):
        if name == "github_discovery": boost += 0.55
        if name in {"github_learning", "web_research"}: boost -= 0.18
    if re.search(r"\bmatch\s+skills?\b", n, re.I):
        if name == "skill_selection": boost += 0.58
        if name == "skill_discovery": boost -= 0.22
    if re.search(r"\b(?:recent|latest|newest)\s+(?:academic\s+)?papers?\b", n, re.I):
        if name == "scientific_research": boost += 0.50
    if re.search(r"\b(?:rag\s+(?:provenance|temporal|retrieval)|indexed\s+documents?)\b", n, re.I):
        if name == "rag_reasoning": boost += 0.52

    if re.search(r"\bgithub\b", n, re.I):
        if name in {"github_discovery", "github_learning"}: boost += 0.30
        if name == "rag_reasoning": boost -= 0.10
    if re.search(r"\b(?:architecture|stack|repository|repo|codebase)\b|هيكل المشروع|مستودع", n, re.I):
        if name == "github_learning" and "github" in n: boost += 0.22
        if name == "development_inspection" and "github" not in n: boost += 0.14
    if re.search(r"\b(?:compile|build|tests?|test suite|validation|verify)\b|يبني|اختبر|تحقق", n, re.I) and name == "development_validation":
        boost += 0.25
    if re.search(r"\b(?:save|store)\s+(?:the\s+)?(?:result|output)\s+as\b|احفظ (?:النتيجة|الناتج) باسم", n, re.I):
        if name == "remember_result": boost += 0.45
        if name == "save_note": boost -= 0.20
    if re.search(r"\b(?:previous|last)\s+(?:result|output)\s+as\b|النتيجة (?:السابقة|السابق) باسم|الناتج السابق باسم", n, re.I):
        if name == "remember_last_result": boost += 0.52
        if name == "remember_result": boost -= 0.08
    if re.search(r"\b(?:forget|delete|erase|remove)\b|انس|امسح|احذف", n, re.I) and name == "forget_fact":
        boost += 0.30
    return boost


def _is_standalone_social(text: str, intent: str) -> bool:
    n = normalize(text)
    patterns = {
        "greeting": r"(?:hello|hi|hey)(?:\s+(?:there|everyone|again|abdullah))?|good\s+(?:morning|afternoon|evening|day)|اهلا(?:\s+وسهلا)?(?:\s+بيك)?|السلام\s+عليكم|ازيك|عامل\s+ايه",
        "how_are_you": r"how\s+are\s+you(?:\s+doing)?|how(?:\s+is|['’]s)\s+it\s+going|what['’]s\s+up|how\s+are\s+things|عامل\s+ايه\s+اخبارك",
        "thanks": r"thanks?(?:\s+(?:a\s+lot|so\s+much))?|thank\s+you(?:\s+so\s+much)?|much\s+appreciated|شكرا|متشكر(?:ة)?|تسلم",
        "goodbye": r"goodbye|bye|see\s+you(?:\s+later)?|take\s+care|مع\s+السلامة|سلام",
        "acknowledgement": r"ok(?:ay)?|got\s+it|understood|sure|تمام|ماشي|حاضر",
    }
    return bool(re.fullmatch(rf"(?:{patterns[intent]})[!?.؟،,\s]*", n, re.I))


def candidates(text: str) -> list[IntentCandidate]:
    u = understand(text)
    by_name: dict[str, IntentCandidate] = {}
    for i in u.intents:
        capability = ROUTES.get(i.name, ((), ""))[1]
        by_name[i.name] = IntentCandidate(i.name, min(0.99, i.score / 7.0), tuple(i.evidence), capability, source="legacy")

    scored: list[tuple[str, float, str]] = []
    for name, (examples, capability) in ROUTES.items():
        raw = _route_score(text, examples)
        adjusted = max(0.0, min(0.99, raw + _context_boost(text, name)))
        if adjusted >= 0.14:
            scored.append((name, adjusted, capability))
            old = by_name.get(name)
            if old is None or adjusted > old.confidence:
                evidence = ("semantic-route-similarity",) + (("semantic-context-boost",) if _context_boost(text, name) > 0 else ())
                by_name[name] = IntentCandidate(name, adjusted, evidence, capability, source="semantic-router")

    # Arabic-Retrieval-v1.0 provides semantic similarity between the user utterance and
    # audited intent exemplars. It expands paraphrase recall without giving the model
    # authority to invent an executable intent.
    semantic_rows = []
    for name, (examples, _capability) in ROUTES.items():
        for example_index, example in enumerate(examples):
            semantic_rows.append((f"{name}::{example_index}", example))
    try:
        semantic_hits = rank_query_against_texts(text, semantic_rows, top_k=min(40, len(semantic_rows)))
    except Exception:
        mode = os.getenv("SHURY_NLP_MODE", "required").strip().casefold()
        if mode in {"required", "strict"}:
            raise
        semantic_hits = []
    semantic_by_name: dict[str, list[float]] = {}
    for hit in semantic_hits:
        name = hit.name.split("::", 1)[0]
        semantic_by_name.setdefault(name, []).append(hit.score)
    for name, scores in semantic_by_name.items():
        # Use the strongest exemplar and a small mean support term. This keeps one
        # unusually close sentence from completely dominating explicit lexical rules.
        strongest = max(scores)
        support = sum(sorted(scores, reverse=True)[:3]) / max(1, min(3, len(scores)))
        semantic_score = max(0.0, min(0.99, 0.78 * strongest + 0.22 * support))
        old = by_name.get(name)
        combined = semantic_score if old is None else min(0.99, 0.68 * old.confidence + 0.32 * semantic_score)
        evidence = ("arabic-retrieval-v1.0", "intent-exemplar-similarity")
        if old is None or combined > old.confidence:
            by_name[name] = IntentCandidate(
                name, combined, old.evidence + evidence if old else evidence,
                ROUTES[name][1], old.required_slots if old else (), old.missing_slots if old else (),
                "retrieval-semantic",
            )

    # Social turns are not fuzzy route families. Require a standalone phrase so
    # semantic similarity cannot turn an ordinary request into a social intent.
    for name in ("greeting", "how_are_you", "thanks", "goodbye", "acknowledgement"):
        if name in by_name and not _is_standalone_social(text, name):
            by_name.pop(name, None)

    # Do not let a single exact lexical cue such as "github" or "repository" erase a
    # stronger semantic route. Context boosts above are intentionally small and auditable.
    result = list(by_name.values())
    if not result:
        return []
    # Convert to a probability-like distribution while preserving meaningful confidence.
    max_conf = max(i.confidence for i in result)
    weights = []
    for i in result:
        weight = math.exp(4.2 * (i.confidence - max_conf))
        weights.append((i, weight))
    denom = sum(w for _, w in weights) or 1.0
    normalized = [
        IntentCandidate(i.name, max(0.0, min(0.99, w / denom)), i.evidence, i.capability,
                        i.required_slots, i.missing_slots, i.source)
        for i, w in weights
    ]
    normalized.sort(key=lambda x: (-x.confidence, x.name))
    return normalized[:10]

from __future__ import annotations
import re
from app.intelligence.understanding import normalize
from app.knowledge.web_research import _tokens
from app.knowledge.agentic_rag.models import ResearchPlan, SubQuestion

_WEB = ("latest", "newest", "today", "current", "internet", "web", "online", "arxiv", "github",
        "أحدث", "الجديد", "اليوم", "حالي", "الإنترنت", "الانترنت", "الويب", "أبحاث", "ابحاث")
_LOCAL = ("document", "documents", "file", "files", "indexed", "knowledge base", "corpus", "في الملف", "من المصادر")

def _split_subquestions(query: str) -> list[str]:
    text = str(query or "").strip()
    parts = re.split(r"\s+(?:and|then|also|plus|و|ثم|وكذلك|وكمان|أيضًا|ايضا|بالإضافة إلى|بالاضافة الى)\s+|[؛;]", text, flags=re.I)
    parts = [p.strip(" .,!؟?") for p in parts if len(p.strip()) >= 8]
    if 1 < len(parts) <= 5:
        return parts
    # A question containing multiple explicit question marks may hide multiple subgoals.
    qparts = [p.strip(" .,!؟?") for p in re.split(r"[؟?]+", text) if len(p.strip()) >= 8]
    return qparts[:5] if len(qparts) > 1 else [text]


def build_plan(query: str, semantic=None, max_rounds: int = 3, max_evidence: int = 24) -> ResearchPlan:
    text = str(query or "").strip()
    norm = normalize(text)
    fresh = bool(getattr(semantic, "requires_fresh_data", False)) or any(x in norm for x in _WEB)
    local_signal = any(x in norm for x in _LOCAL)
    if fresh and local_signal:
        route = "hybrid"
    elif fresh:
        route = "web"
    else:
        route = "local"

    raw_parts = _split_subquestions(text)
    subs = []
    for i, part in enumerate(raw_parts, 1):
        n = normalize(part)
        subfresh = fresh or any(x in n for x in _WEB)
        subroute = "hybrid" if subfresh and local_signal else ("web" if subfresh else "local")
        purpose = "answer"
        if any(x in n for x in ("why", "سبب", "explain", "اشرح", "كيف", "how")):
            purpose = "explain"
        elif any(x in n for x in ("compare", "comparison", "قارن", "مقارنة")):
            purpose = "compare"
        queries = (part,)
        deps = (f"q{i-1}",) if i > 1 and any(x in n for x in ("who", "what did", "what does", "الذي", "التي", "من", "ماذا فعل")) else ()
        subs.append(SubQuestion(id=f"q{i}", question=part, purpose=purpose, route=subroute, queries=queries, dependencies=deps))
    rationale = []
    if fresh:
        rationale.append("freshness signal detected: allow web retrieval")
    if len(subs) > 1:
        rationale.append("multiple information needs detected: track coverage per sub-question")
    if route == "local":
        rationale.append("no explicit freshness signal: start with indexed knowledge")
    else:
        rationale.append("use external evidence only as untrusted, verifiable data")
    prefs = ["official/primary", "recent", "domain-diverse"] if fresh else ["user-provided/indexed", "relevant"]
    return ResearchPlan(text, route, subs, max_rounds=max_rounds, max_evidence=max_evidence, rationale=rationale, source_preferences=prefs)

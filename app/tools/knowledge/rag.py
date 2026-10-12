from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path
from app.knowledge.rag import RAGEngine, rag_index, rag_index_memory
from app.knowledge.rag_v16 import AdaptiveRAGEngine
import re


def _path(goal: str) -> str:
    m = re.search(r'["\']([^"\']+)["\']', goal)
    if m:
        return m.group(1)
    m = re.search(r'((?:[A-Za-z]:[\\/]|/)[^\n]+?)(?:\s+(?:عن|for|ثم|and)\s+|$)', goal)
    if m:
        return m.group(1).strip().rstrip('.,')
    for marker in ("index ", "فهرس ", "افهرس ", "اعمل فهرسة "):
        pos = goal.casefold().find(marker.casefold())
        if pos >= 0:
            return goal[pos + len(marker):].strip()
    return goal.strip()


def _query(goal: str) -> str:
    quoted = re.findall(r'["\']([^"\']+)["\']', goal)
    if quoted:
        return quoted[-1]
    markers = ("اسأل ", "اسال ", "answer ", "rag ", "ابحث في المعرفة عن ", "استرجع الأدلة عن ", "retrieve ")
    for marker in markers:
        pos = goal.casefold().find(marker.casefold())
        if pos >= 0:
            return goal[pos + len(marker):].strip()
    return goal.strip()


@tool(
    "فهرسة مصادر المعرفة محليًا باستخدام RAG هجين مع Arabic-Retrieval-v1.0",
    {"path": "str"},
    name="index_knowledge",
    triggers=("index knowledge", "index corpus", "فهرس المعرفة", "افهرس المعرفة", "فهرسة المعرفة", "knowledge base"),
    match=lambda g: any(x in g.casefold() for x in ("index knowledge", "index corpus", "فهرس المعرفة", "افهرس المعرفة", "فهرسة المعرفة", "knowledge base")),
    build_args=lambda g: {"path": _path(g)},
    capability="rag_indexing",
    produces=("knowledge_indexed",),
    cost=3.0,
    duration=1.0,
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
)
def index_knowledge_tool(path: str):
    return RAGEngine().index_knowledge(str(safe_workspace_path(path)))


@tool(
    "فهرسة الذاكرة المحلية في قاعدة RAG لاستخدامها كمصدر أدلة",
    {},
    name="index_agent_memory",
    triggers=("index agent memory", "فهرس الذاكرة", "افهرس الذاكرة", "rag memory"),
    match=lambda g: any(x in g.casefold() for x in ("index agent memory", "فهرس الذاكرة", "افهرس الذاكرة", "rag memory")),
    capability="rag_memory_indexing",
    produces=("agent_memory_indexed",),
    cost=2.0,
    duration=0.5,
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
)
def index_agent_memory_tool():
    return rag_index_memory()


@tool(
    "حذف مصدر من قاعدة معرفة SHURY مع الحفاظ على فصلها عن الذاكرة الشخصية",
    {"source_ref": "str"},
    name="remove_knowledge",
    triggers=("remove knowledge", "delete knowledge", "احذف من المعرفة", "احذف مصدر المعرفة"),
    match=lambda g: any(x in g.casefold() for x in ("remove knowledge", "delete knowledge", "احذف من المعرفة", "احذف مصدر المعرفة")),
    build_args=lambda g: {"source_ref": _query(g)},
    capability="rag_indexing",
    produces=("knowledge_removed",),
    cost=0.5,
    duration=0.2,
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
)
def remove_knowledge_tool(source_ref: str):
    from app.knowledge.knowledge_base import KnowledgeBase
    return {"removed": KnowledgeBase().remove(source_ref), "source_ref": source_ref}


@tool(
    "عرض مصادر المعرفة الحالية مع scope والمشروع وprovenance",
    {},
    name="list_knowledge",
    triggers=("list knowledge", "knowledge sources", "مصادر المعرفة", "قائمة المعرفة"),
    match=lambda g: any(x in g.casefold() for x in ("list knowledge", "knowledge sources", "مصادر المعرفة", "قائمة المعرفة")),
    build_args=lambda g: {},
    capability="rag_indexing",
    produces=("knowledge_listed",),
    cost=0.3,
    duration=0.1,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
)
def list_knowledge_tool():
    from app.knowledge.knowledge_base import KnowledgeBase
    return {"sources": KnowledgeBase().list(), "policy": "world/project knowledge only; personal memory is excluded"}


@tool(
    "استرجاع أدلة تكيفي يختار استراتيجية RAG حسب تعقيد السؤال ويستخدم hybrid retrieval وset-cover وadaptive escalation وUCB محلياً مع إجابة استخراجية موثقة",
    {"query": "str"},
    name="rag_query",
    triggers=("rag", "retrieval augmented", "retrieve evidence", "استرجع الأدلة", "ابحث في المعرفة", "اسأل المعرفة", "من المصادر"),
    match=lambda g: any(x in g.casefold() for x in ("rag", "retrieval augmented", "retrieve evidence", "indexed documents", "indexed document", "provenance", "temporal memory", "استرجع الأدلة", "ابحث في المعرفة", "اسأل المعرفة", "من المصادر"))
          and not any(x in g.casefold() for x in ("rag portfolio", "retrieval portfolio", "خبرة rag", "خبرة الاسترجاع", "استراتيجيات rag"))
          and not ("web research" in g.casefold() or "research the web" in g.casefold() or "search online" in g.casefold()
                   or "search the internet" in g.casefold() or "newest research" in g.casefold() or "latest research" in g.casefold()
                   or "ابحث على الانترنت" in g.casefold() or "ابحث على الإنترنت" in g.casefold()),
    build_args=lambda g: {"query": _query(g)},
    capability="rag_reasoning",
    produces=("retrieved_evidence",),
    cost=2.5,
    duration=0.8,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=4,
)
def rag_query_tool(query: str):
    return AdaptiveRAGEngine().query(query)


@tool(
    "عرض خبرة استراتيجيات RAG المتراكمة حسب سياق السؤال مع المتوسط والـobservations",
    {},
    name="analyze_rag_portfolio",
    triggers=("rag portfolio", "retrieval portfolio", "خبرة rag", "خبرة الاسترجاع", "استراتيجيات rag"),
    match=lambda g: any(x in g.casefold() for x in ("rag portfolio", "retrieval portfolio", "خبرة rag", "خبرة الاسترجاع", "استراتيجيات rag")),
    capability="rag_learning",
    produces=("rag_portfolio_analyzed",),
    cost=0.8,
    duration=0.1,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=10,
)
def analyze_rag_portfolio_tool():
    conn = RAGEngine()._connect()
    try:
        rows = conn.execute(
            "SELECT context_key,strategy,COUNT(*),AVG(reward),SUM(grounded),MAX(ts) "
            "FROM retrieval_observations GROUP BY context_key,strategy ORDER BY context_key,strategy"
        ).fetchall()
    finally:
        conn.close()
    observations = [
        {"context_key": c, "strategy": s, "observations": n, "mean_reward": round(float(r), 6),
         "grounded_observations": int(g), "last_seen": ts}
        for c, s, n, r, g, ts in rows
    ]
    return {
        "observations": observations,
        "count": len(observations),
        "policy": "current-data-evidence-first + recency-weighted UCB",
        "note": "retrieval rewards measure operational evidence utility, not ground-truth answer accuracy",
    }

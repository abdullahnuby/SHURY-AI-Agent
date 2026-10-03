from app.runtime.registry import tool
from app.services.agentic_rag_service import agentic_rag


def _query(goal: str) -> str:
    text = str(goal or "").strip()
    for marker in ("agentic rag", "agentic retrieval", "ابحث بشكل تكراري", "بحث وكيل", "evidence loop", "agentic research"):
        pos = text.casefold().find(marker.casefold())
        if pos >= 0:
            rest = text[pos + len(marker):].strip(" :,-")
            if rest:
                return rest
    return text


@tool(
    "Agentic RAG: يخطط لسؤال البحث، يوزع local/web retrieval، يكرر البحث عند نقص الأدلة، يبني evidence ledger، يكشف التعارضات، ويتحقق من كل citation قبل الإجابة",
    {"query": "str"},
    name="agentic_rag",
    triggers=("agentic rag", "agentic retrieval", "evidence loop", "agentic research", "ابحث بشكل تكراري", "بحث وكيل"),
    match=lambda g: any(x in g.casefold() for x in ("agentic rag", "agentic retrieval", "evidence loop", "agentic research", "ابحث بشكل تكراري", "بحث وكيل")),
    build_args=lambda g: {"query": _query(g)},
    capability="agentic_rag",
    produces=("verified_evidence", "grounded_answer", "research_trace"),
    cost=5.0,
    duration=4.0,
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
    intent_priority=11, exploration_safe=True, emits_world_delta=False,
    information_domains=("research", "knowledge", "learning"), information_gain_prior=0.90,
)
def agentic_rag_tool(query: str):
    return agentic_rag(query)

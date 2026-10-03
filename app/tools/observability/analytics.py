from app.runtime.registry import tool
from app.knowledge.memory import get_memory
from app.observability.agent_analytics import analyze_runtime

@tool(
    "تحليل أداء الـAgent من سجل التنفيذ المحلي",
    {},
    name="analyze_runtime",
    triggers=("حلل أداء", "تحليل الاداء", "analytics", "runtime analytics", "حلل السجل"),
    capability="agent_observability",
    produces=("runtime_analyzed",),
    cost=1.0,
    duration=0.2,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
)
def analyze_runtime_tool():
    return analyze_runtime(get_memory())


@tool(
    "عرض خبرة خوارزميات التحليل المتراكمة مع السياق وعدد الملاحظات، بدون تغيير الخطة تلقائيًا",
    {},
    name="analyze_algorithm_portfolio",
    triggers=("algorithm portfolio", "adaptive algorithms", "خبرة الخوارزميات", "اختيار الخوارزمية"),
    capability="agent_learning",
    produces=("algorithm_portfolio_analyzed",),
    cost=0.8,
    duration=0.1,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
)
def analyze_algorithm_portfolio_tool():
    memory = get_memory()
    snapshot = memory.algorithm_portfolio_snapshot()
    return {
        "observations": snapshot,
        "count": len(snapshot),
        "policy": "evidence_first_with_recency_weighted_ucb_tiebreak",
        "note": "rewards measure operational evidence utility, not ground-truth statistical accuracy",
    }

from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path
from app.services.adaptive_analysis_service import adaptive_analyze, compare_numeric_effect
from app.knowledge.memory import get_memory
from app.tools.data.analysis import _extract_path


@tool(
    "تحليل شامل متكيف: اختيار خوارزمية مبني على البيانات + خبرة تاريخية قابلة للتدقيق",
    {"path": "str"},
    name="diagnose_dataset",
    triggers=("comprehensive analysis", "diagnose dataset", "تشخيص البيانات", "تحليل شامل", "حلل البيانات بالكامل"),
    match=lambda g: any(x in g.casefold() for x in (
        "comprehensive analysis", "diagnose dataset", "تشخيص البيانات", "تحليل شامل", "حلل البيانات بالكامل",
    )) and any(ext in g.casefold() for ext in (".csv", ".json", ".sqlite", ".db")),
    build_args=lambda g: {"path": _extract_path(g)},
    capability="data_analysis",
    produces=("dataset_diagnosed", "analysis_evidence"),
    cost=3.5,
    duration=1.0,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
)
def diagnose_dataset_tool(path: str):
    memory = get_memory()
    report = adaptive_analyze(str(safe_workspace_path(path)), memory=memory)
    learned = []
    for item in report.get("adaptive_learning", []):
        evidence = float(item.get("evidence_score") or 0.0)
        reward = 0.6 + 0.4 * max(0.0, min(1.0, evidence)) if report.get("verified") else 0.0
        memory.record_algorithm_observation(
            item["context"], item["method"], reward, verified=bool(report.get("verified")),
            metadata={"source": str(path), "evidence_score": evidence,
                      "note": "operational evidence utility; not ground-truth accuracy"},
        )
        learned.append({**item, "recorded_reward": reward})
    report["adaptive_learning"] = learned
    return report

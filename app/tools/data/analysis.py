from pathlib import Path
import os

from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path
from app.knowledge.data_analysis import DeterministicDataAgent, DataAnalysisError

_agent = DeterministicDataAgent()
_SUPPORTED_DATA = {".csv", ".json", ".sqlite", ".sqlite3", ".db"}
ACTIVE_DATASET_REF = "@active_dataset"


def _workspace_root() -> Path:
    raw = os.getenv("AGENT_WORKSPACE")
    return Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()


def _resolve_active_dataset() -> str:
    root = _workspace_root()
    if not root.exists() or not root.is_dir():
        raise DataAnalysisError(f"مساحة العمل غير موجودة: {root}")
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.casefold() in _SUPPORTED_DATA
    )
    if not files:
        raise DataAnalysisError("لم أجد ملف بيانات مدعومًا في مساحة العمل")
    if len(files) > 1:
        names = ", ".join(str(p.relative_to(root)) for p in files[:8])
        extra = " ..." if len(files) > 8 else ""
        raise DataAnalysisError(f"وجدت أكثر من dataset في مساحة العمل؛ حدّد الملف صراحة: {names}{extra}")
    return str(files[0].relative_to(root))


def _resolve_data_reference(path: str) -> str:
    return _resolve_active_dataset() if path == ACTIVE_DATASET_REF else path


def _extract_path(goal: str) -> str:
    import re
    text = goal.strip()
    m = re.search(r'["\']([^"\']+)["\']', text)
    if m:
        return m.group(1)
    # Prefer a concrete file token so the remainder can stay as the question.
    m = re.search(r'([^\s]+\.(?:csv|json|sqlite3?|db))\b', text, re.I)
    if m:
        return m.group(1)
    generic_targets = {
        "the dataset", "the data", "dataset", "data", "anomalies", "outliers",
        "trends", "correlations", "ملف البيانات", "البيانات", "القيم الشاذة", "الشذوذ",
    }
    for marker in ("حلل ملف ", "حلل ", "analyze ", "profile "):
        pos = text.casefold().find(marker.casefold())
        if pos >= 0:
            tail = text[pos + len(marker):].strip()
            if " عن " in tail:
                tail = tail.split(" عن ", 1)[0].strip()
            if tail.casefold().rstrip(" .,!؟") in generic_targets:
                return ACTIVE_DATASET_REF
            return tail
    # A bare semantic reference like "the dataset" is an active-workspace reference,
    # not a literal filename. The runtime resolves it only when the workspace has exactly one supported dataset.
    if text.casefold().rstrip(" .,!؟") in generic_targets:
        return ACTIVE_DATASET_REF
    return text


@tool(
    "تحليل ملف محلي وإرجاع evidence إحصائي قابل لإعادة الإنتاج",
    {"path": "str"},
    name="profile_dataset",
    triggers=("profile dataset", "dataset profile", "data profile", "profile the dataset", "schema", "بروفايل البيانات", "بروفايل للبيانات", "هيكل البيانات", "اعمل بروفايل"),
    match=lambda g: any(x in g.casefold() for x in ("profile dataset", "dataset profile", "data profile", "profile the dataset", "profile the data", "profile data", "schema", "بروفايل البيانات", "بروفايل للبيانات", "هيكل البيانات", "اعمل بروفايل")),
    build_args=lambda g: {"path": _extract_path(g)},
    capability="data_analysis",
    produces=("dataset_profiled",),
    cost=2.0,
    duration=0.5,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
)
def profile_dataset_tool(path: str):
    return _agent.profile(str(safe_workspace_path(_resolve_data_reference(path))))


@tool(
    "سؤال تحليلي محدد على ملف محلي بدون تنفيذ كود خارجي",
    {"path": "str", "question": "str"},
    name="analyze_dataset",
    triggers=("analyze", "analysis", "حلل", "متوسط", "average", "mean", "correlation", "ارتباط", "outlier", "anomal", "شذوذ"),
    match=lambda g: (
        not any(x in g.casefold() for x in ("comprehensive analysis", "تشخيص البيانات", "تحليل شامل", "حلل البيانات بالكامل"))
        and any(x in g.casefold() for x in ("analyze ", "analysis ", "average ", "mean ", "what is the average", "find the average", "حلل ", "متوسط ", "correlation", "ارتباط", "outlier", "anomal", "شذوذ", "القيم الشاذة"))
        and (any(ext in g.casefold() for ext in (".csv", ".json", ".sqlite", ".db")) or any(x in g.casefold() for x in ("dataset", "data file", "ملف البيانات")))
    ),
    build_args=lambda g: {"path": _extract_path(g), "question": g},
    capability="data_analysis",
    produces=("analysis_evidence",),
    cost=2.5,
    duration=0.7,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=9,
)
def analyze_dataset_tool(path: str, question: str):
    return _agent.ask(str(safe_workspace_path(_resolve_data_reference(path))), question)
